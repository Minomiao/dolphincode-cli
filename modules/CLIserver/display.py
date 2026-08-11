"""帮助、工具、技能显示界面。"""
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from modules.logger import get_logger
from . import i18n
from .state import state
from .screen_refresh import create_header_panel, create_footer_panel

log = get_logger("Dolphin.display")
_console = Console()


def show_help():
    """显示命令帮助界面。"""
    cmd = state.cmd

    def _render():
        commands_config = cmd.load_commands()
        cmd_list = commands_config.get("commands", {})

        log.info("显示帮助信息")

        # 构建表格
        table = Table(show_header=True, header_style="bold cyan", border_style="dim", padding=(0, 2))
        table.add_column("命令", style="bold white", width=15)
        table.add_column("描述", style="dim")

        for cmd_key, cmd_info in cmd_list.items():
            cmd_input = cmd_info.get("input", "")
            cmd_description = cmd_info.get("description", "")
            table.add_row(cmd_input, cmd_description)

        # 渲染界面
        _console.print()
        _console.print(create_header_panel(i18n.t("help.title"), i18n.t("help.subtitle")))
        _console.print()
        _console.print(table)
        _console.print()
        _console.print(create_footer_panel(i18n.t("display.back_hint")))
        input()

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('help'),
                 command_info=f"╰─{cmd.get_command_description('help')}")


def show_tools():
    """显示可用工具界面。"""
    cmd = state.cmd

    def _render():
        tools = state.chat_instance.list_available_tools()
        log.info(f"显示可用工具，共 {len(tools)} 个")

        _console.print()
        _console.print(create_header_panel(i18n.t("tools.title"), i18n.t("tools.subtitle", count=len(tools))))

        if tools:
            table = Table(show_header=True, header_style="bold cyan", border_style="dim", padding=(0, 2))
            table.add_column("#", style="dim", width=4)
            table.add_column("工具名称", style="bold white", width=20)
            table.add_column("描述", style="dim")

            for i, tool in enumerate(tools, 1):
                table.add_row(str(i), tool['name'], tool.get('description', ''))

            _console.print()
            _console.print(table)
        else:
            _console.print()
            _console.print(Panel(Text(i18n.t("tools.no_tools"), style="yellow"), border_style="yellow"))

        _console.print()
        _console.print(create_footer_panel(i18n.t("display.back_hint")))
        input()

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('tools'),
                 command_info=f"╰─{cmd.get_command_description('tools')}")


def show_skills():
    """技能管理界面（上下键导航，Enter 切换状态）。"""
    cmd = state.cmd
    log.info("显示技能管理")

    skills = state.chat_instance.list_skills()
    if not skills:
        print(f"\n{i18n.t('skills.no_skills')}")
        return

    def _render():
        from .key_nav import navigate

        def _label(skill, i):
            status = i18n.t("tools.enabled") if skill.get('enabled', True) else i18n.t("tools.disabled")
            return (f"{skill['name']}\n"
                    f"{skill.get('description', '')}\n"
                    f"[{status}]")

        def _toggle(skill, i):
            skill_name = skill['name']
            current_status = skill.get('enabled', True)
            target_status = not current_status

            if skill_name.startswith("plugin-"):
                result = state.chat_instance.plugin_loader.toggle_skill(skill_name, target_status)
            elif skill_name.startswith("stdskill-"):
                result = state.chat_instance.std_loader.toggle_skill(skill_name, target_status)
            else:
                result = state.chat_instance.skill_mgr.toggle_skill(skill_name, target_status)

            if result.get('success'):
                new_status_text = i18n.t("tools.enabled") if target_status else i18n.t("tools.disabled")
                skill['enabled'] = target_status
                _console.print(f"[green]{i18n.t('skills.toggled', name=skill_name, status=new_status_text)}[/green]")
            else:
                _console.print(f"[red]{i18n.t('main.error', error=result.get('error'))}[/red]")
            return False  # 继续导航，可连续切换多个技能

        navigate(i18n.t("skills.title"), i18n.t("skills.subtitle", count=len(skills)),
                 skills, _label, _toggle,
                 i18n.t("skills.hint"),
                 line_height=3)

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('skills'),
                 command_info=f"╰─{cmd.get_command_description('skills')}")
