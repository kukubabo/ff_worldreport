# M-QA-5: 명시적 import — star import 제거.
import traceback

from plugin import create_plugin_instance

setting = {
    'filepath': __file__,
    'use_db': True,
    'use_default_setting': True,
    'home_module': None,
    'menu': {
        'uri': __package__,
        'name': '특파원보고 세계는 지금',
        'list': [
            {
                'uri': 'basic/setting',
                'name': '설정'
            },
            {
                'uri': 'basic/list',
                'name': '다운로드 이력'
            },
            {
                'uri': 'log',
                'name': '로그'
            }
        ]
    },
    'setting_menu': None,
    'default_route': 'normal'
}

P = create_plugin_instance(setting)

try:
    from .mod_basic import ModuleBasic
    P.set_module_list([ModuleBasic])
except Exception as e:
    P.logger.error(f'Exception:{str(e)}')
    P.logger.error(traceback.format_exc())