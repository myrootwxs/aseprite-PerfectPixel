-- PerfectPixel Extension for Aseprite
-- AI 像素画逆向还原、对齐精修与色彩量化工具

local function find_cli_command(plugin_path)
    -- 1. 优先寻找扩展自带的独立 exe
    local exe_path = app.fs.joinPath(plugin_path, "bin", "perfect_pixel_cli.exe")
    if app.fs.isFile(exe_path) then
        return string.format('"%s"', exe_path)
    end

    -- 2. 检查开发态的 CLI Python 脚本
    local py_script = app.fs.joinPath(plugin_path, "bin", "perfect_pixel_cli.py")
    if not app.fs.isFile(py_script) then
        py_script = app.fs.joinPath(plugin_path, "..", "perfect_pixel_cli.py")
    end

    if app.fs.isFile(py_script) then
        -- 尝试常见 python 启动器
        return string.format('python "%s"', py_script)
    end

    return nil
end

local function run_perfect_pixel(plugin)
    local sprite = app.activeSprite
    if not sprite then
        app.alert{ title="PerfectPixel", text="请先在 Aseprite 中打开需要精修的图片！" }
        return
    end

    local cli_cmd = find_cli_command(plugin.path)
    if not cli_cmd then
        app.alert{
            title="未找到执行后端",
            text="插件未检测到 perfect_pixel_cli.exe 或 Python 运行环境。\n请确保扩展包中包含 bin/perfect_pixel_cli.exe。"
        }
        return
    end

    -- 构建 Aseprite 像素风参数对话框
    local dlg = Dialog{ title="PerfectPixel 像素画精修" }

    dlg:separator{ text="像素网格对齐" }
    dlg:number{
        id="grid_w",
        label="目标网格宽:",
        text="0",
        decimals=0
    }
    dlg:number{
        id="grid_h",
        label="目标网格高:",
        text="0",
        decimals=0
    }
    dlg:label{
        text="* 宽和高留 0 则代表自动检测真实像素块大小"
    }

    dlg:separator{ text="采样与量化" }
    dlg:combobox{
        id="sample_method",
        label="采样方式:",
        option="center",
        options={ "center", "majority", "median" }
    }
    dlg:slider{
        id="max_colors",
        label="最大颜色数:",
        min=0,
        max=64,
        value=0
    }
    dlg:combobox{
        id="scale",
        label="输出放大倍数:",
        option="1x (原尺寸)",
        options={ "1x (原尺寸)", "2x", "4x", "8x", "16x" }
    }

    -- 智能吸取当前画布(0,0)像素作为默认背景色参考
    local default_bg_color = Color{ r=255, g=255, b=255 }
    if sprite and sprite.cels and #sprite.cels > 0 then
        local first_cel = sprite.cels[1]
        if first_cel and first_cel.image then
            local p = first_cel.image:getPixel(0, 0)
            local r = app.pixelColor.rgbaR(p)
            local g = app.pixelColor.rgbaG(p)
            local b = app.pixelColor.rgbaB(p)
            default_bg_color = Color{ r=r, g=g, b=b }
        end
    end

    dlg:separator{ text="透明背景去除优化" }
    dlg:check{
        id="remove_bg",
        label="启用去除背景",
        selected=false
    }
    dlg:combobox{
        id="bg_mode",
        label="抠图模式:",
        option="仅外部连通背景 (保护内部同色 - 推荐)",
        options={
            "仅外部连通背景 (保护内部同色 - 推荐)",
            "全图相同颜色 (全局抠除)"
        }
    }
    dlg:combobox{
        id="bg_source",
        label="背景取色:",
        option="手动拾取 / 下方色块",
        options={
            "手动拾取 / 下方色块",
            "自动检测 (从边角推断)"
        }
    }
    dlg:color{
        id="bg_color",
        label="目标背景色:",
        color=default_bg_color
    }
    dlg:slider{
        id="bg_tolerance",
        label="背景色容差:",
        min=0,
        max=128,
        value=30
    }
    dlg:check{
        id="bg_defringe",
        label="消除边缘晕染与白边杂色 (Defringe)",
        selected=true
    }

    dlg:separator{ text="输出方式" }
    dlg:combobox{
        id="output_mode",
        label="输出目标:",
        option="新建 Sprite 打开 (推荐)",
        options={ "新建 Sprite 打开 (推荐)", "作为新图层插入当前 Sprite" }
    }

    dlg:button{ id="ok", text="开始精修" }
    dlg:button{ id="cancel", text="取消" }

    dlg:show()
    local data = dlg.data
    if not data.ok then return end

    -- 准备临时文件路径
    local temp_in = app.fs.joinPath(app.fs.tempPath, "pp_ase_in.png")
    local temp_out = app.fs.joinPath(app.fs.tempPath, "pp_ase_out.png")

    -- 导出当前活跃画面的副本
    sprite:saveCopyAs(temp_in)

    -- 解析参数
    local grid_w = tonumber(data.grid_w) or 0
    local grid_h = tonumber(data.grid_h) or 0
    local max_colors = tonumber(data.max_colors) or 0
    local sample_method = data.sample_method or "center"

    local scale_factor = 1
    if data.scale == "2x" then scale_factor = 2
    elseif data.scale == "4x" then scale_factor = 4
    elseif data.scale == "8x" then scale_factor = 8
    elseif data.scale == "16x" then scale_factor = 16
    end

    -- 组装 CLI 命令
    local cmd_parts = {
        cli_cmd,
        string.format('"%s"', temp_in),
        string.format('-o "%s"', temp_out),
        string.format('--grid-w %d', grid_w),
        string.format('--grid-h %d', grid_h),
        string.format('--sample-method %s', sample_method),
        string.format('--max-colors %d', max_colors),
        string.format('--scale %d', scale_factor),
        '--json'
    }

    if data.remove_bg then
        local bg_color_arg = "auto"
        if data.bg_source == "手动拾取 / 下方色块" and data.bg_color then
            bg_color_arg = string.format("#%02x%02x%02x", data.bg_color.red, data.bg_color.green, data.bg_color.blue)
        end
        local tol = tonumber(data.bg_tolerance) or 30
        local mode_param = "contiguous"
        if data.bg_mode == "全图相同颜色 (全局抠除)" then
            mode_param = "global"
        end

        table.insert(cmd_parts, string.format('--bg-color "%s"', bg_color_arg))
        table.insert(cmd_parts, string.format('--bg-tolerance %d', tol))
        table.insert(cmd_parts, string.format('--bg-mode %s', mode_param))
        if data.bg_defringe then
            table.insert(cmd_parts, '--bg-defringe')
        else
            table.insert(cmd_parts, '--no-bg-defringe')
        end
    end

    -- 先清理可能存在的历史临时文件
    if app.fs.isFile(temp_out) then
        os.remove(temp_out)
    end

    local final_cmd = table.concat(cmd_parts, " ")

    -- 提示用户正在后台处理，消除卡顿死机感
    app.status = "PerfectPixel: 正在极速提纯像素与处理透明背景…"
    app.refresh()

    local is_windows = package.config:sub(1,1) == "\\"
    local exit_code = 0

    if is_windows then
        -- Windows 下通过 WScript.Shell 的 SW_HIDE (0) 模式唤起，实现 100% 纯静默执行，绝无任何黑框终端弹出
        local temp_vbs = app.fs.joinPath(app.fs.tempPath, "pp_silent_run.vbs")
        local f = io.open(temp_vbs, "w")
        if f then
            local escaped_cmd = final_cmd:gsub('"', '""')
            f:write(string.format('CreateObject("WScript.Shell").Run "%s", 0, True\n', escaped_cmd))
            f:close()
            exit_code = os.execute(string.format('wscript.exe "%s"', temp_vbs))
            if app.fs.isFile(temp_vbs) then
                os.remove(temp_vbs)
            end
        else
            exit_code = os.execute(string.format('"%s"', final_cmd))
        end
    else
        exit_code = os.execute(final_cmd)
    end

    app.status = "PerfectPixel: 精修完成！"
    app.refresh()

    if app.fs.isFile(temp_out) then
        if data.output_mode == "新建 Sprite 打开 (推荐)" then
            local new_sprite = app.open(temp_out)
            if new_sprite then
                app.alert{
                    title="精修完成",
                    text=string.format("已成功提纯像素点阵！\n输出尺寸: %d × %d", new_sprite.width, new_sprite.height)
                }
            end
        else
            -- 作为新图层插入当前 Sprite
            local loaded_sprite = app.open(temp_out)
            if loaded_sprite then
                local img = Image(loaded_sprite.spec)
                img:drawSprite(loaded_sprite, 1, Point(0, 0))
                loaded_sprite:close()

                app.transaction("PerfectPixel 精修图层", function()
                    local layer = sprite:newLayer()
                    layer.name = string.format("PerfectPixel_%dx%d", img.width, img.height)
                    sprite:newCel(layer, 1, img, Point(0, 0))
                end)
                app.alert{ title="精修完成", text="已作为新图层载入当前画布！" }
            end
        end
    else
        app.alert{
            title="精修失败",
            text="处理程序未生成目标文件，请检查命令行或参数是否有效。"
        }
    end
end

function init(plugin)
    -- 1. 注册到【图像 (Sprite)】菜单（与 Sprite 属性并列）
    plugin:newCommand{
        id = "PerfectPixelSprite",
        title = "PerfectPixel 像素精修...",
        group = "sprite_properties",
        onclick = function()
            run_perfect_pixel(plugin)
        end
    }

    -- 2. 注册到【编辑 (Edit)】菜单
    plugin:newCommand{
        id = "PerfectPixelEdit",
        title = "PerfectPixel 像素精修...",
        group = "edit_insert",
        onclick = function()
            run_perfect_pixel(plugin)
        end
    }

    -- 3. 注册到【文件 -> 脚本 (File -> Scripts)】官方扩展脚本位置
    plugin:newCommand{
        id = "PerfectPixelScripts",
        title = "PerfectPixel 像素精修...",
        group = "file_scripts",
        onclick = function()
            run_perfect_pixel(plugin)
        end
    }
end

function exit(plugin)
end
