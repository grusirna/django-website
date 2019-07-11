from django.conf import settings


EMPTY_CHANGELIST_VALUE = getattr(settings, 'BASE_EMPTY_CHANGELIST_VALUE', ' ')
FILTER_PREFIX = getattr(settings, 'BASE_FILTER_PREFIX', '_p_')
SEARCH_VAR = getattr(settings, 'BASE_SEARCH_VAR', '_q_')
DEFAULT_MODEL_ICON = getattr(settings, 'BASE_DEFAULT_MODEL_ICON', '')
BUILDIN_STYLES = getattr(settings, 'BASE_BUILDIN_STYLES', {
    'ext': 'website/includes/sitemenu_ext.tpl',
    'default': 'website/includes/sitemenu_default.tpl',
    'accordion': 'website/includes/sitemenu_accordion.tpl',
    'inspinia': 'website/includes/sitemenu_inspinia.tpl'
})
TO_FIELD_VAR = getattr(settings, 'BASE_TO_FIELD_VAR', 't')
SHOW_FIELD_VAR = getattr(settings, 'BASE_SHOW_FIELD_VAR', 's')
ACTION_CHECKBOX_NAME = getattr(settings, 'BASE_ACTION_CHECKBOX_NAME', '_selected_action')
ALL_VAR = getattr(settings, 'BASE_ALL_VAR', 'all')
ORDER_VAR = getattr(settings, 'BASE_ORDER_VAR', 'o')
PAGE_VAR = getattr(settings, 'BASE_PAGE_VAR', 'p')
COL_LIST_VAR = getattr(settings, 'BASE_COL_LIST_VAR', '_cols')
ERROR_FLAG = getattr(settings, 'BASE_ERROR_FLAG', 'e')
DOT = getattr(settings, 'BASE_DOT', '.')
ROOT_PATH_NAME = getattr(settings, 'BASE_ROOT_PATH_NAME', 'website')
EXPORT_MAX = getattr(settings, 'EXPORT_MAX', 10000)
ACTION_NAME = {
    'add': '添加 %s',
    'change': '修改 %s',
    'delete': '删除 %s',

    'edit': '编辑 %s',
    'view': '查看 %s',
}
BATCH_CHECKBOX_NAME = '_batch_change_fields'
RELATE_PREFIX = '_rel_'
vendors = {
    'load-image': {
        'js': 'website/verdor/load-image/load-image.min.js'
    },
    "iCheck": {
        'js': 'website/vendor/iCheck/icheck.min.js'
        ,
        'css': "website/vendor/iCheck/square/blue.css"
    },
    "ionicons": {
        'css': "website/vendor/ionicons/css/ionicons.min.css"
    },
    "adminlte": {
        'js': {
            'dev': ['website/vendor/adminlte/dist/js/app.js',
                    'website/vendor/adminlte/dist/js/setup.js',
                    'website/vendor/adminlte/dist/js/demo.js',
                    'website/vendor/adminlte/dist/js/pages/dashboard.js',
                    'website/vendor/adminlte/dist/js/pages/dashboard2.js'],
            'production': 'website/vendor/adminlte/dist/js/app.min.js',
        },
        'css': {
            'dev': ['website/vendor/adminlte/dist/css/AdminLTE.css',
                    'website/vendor/adminlte/dist/css/skins/_all-skins.css'],
            'production': ['website/vendor/adminlte/dist/css/AdminLTE.min.css',
                           'website/vendor/adminlte/dist/css/skins/_all-skins.min.css'],
        }
    },
    "bootstrap": {
        'js': {
            'dev': 'website/vendor/bootstrap/js/bootstrap.js',
            'production': 'website/vendor/bootstrap/js/bootstrap.min.js',
            'cdn': 'http://netdna.bootstrapcdn.com/twitter-bootstrap/2.3.1/js/bootstrap.min.js'
        },
        'css': {
            'dev': 'website/vendor/bootstrap/css/bootstrap.css',
            'production': 'website/vendor/bootstrap/css/bootstrap.css',
            'cdn': 'http://netdna.bootstrapcdn.com/twitter-bootstrap/2.3.1/css/bootstrap-combined.min.css'
        },
        'responsive': {'css': {
            'dev': 'website/vendor/bootstrap/bootstrap-responsive.css',
            'production': 'website/vendor/bootstrap/bootstrap-responsive.css'
        }}
    },
    'jquery': {
        "js": {
            'dev': 'website/vendor/jquery/jquery.min.js',
            'production': 'website/vendor/jquery/jquery.min.js',
        }
    },
    'jquery-ui-effect': {
        "js": {
            'dev': 'website/vendor/jquery-ui/jquery.ui.effect.js',
            'production': 'website/vendor/jquery-ui/jquery.ui.effect.min.js'
        }
    },
    'jquery-ui-sortable': {
        "js": {
            'dev': ['website/vendor/jquery-ui/jquery.ui.core.js', 'website/vendor/jquery-ui/jquery.ui.widget.js',
                    'website/vendor/jquery-ui/jquery.ui.mouse.js',
                    'website/vendor/jquery-ui/jquery.ui.sortable.js'],
            'production': ['website/vendor/jquery-ui/jquery.ui.core.min.js',
                           'website/vendor/jquery-ui/jquery.ui.widget.min.js',
                           'website/vendor/jquery-ui/jquery.ui.mouse.min.js',
                           'website/vendor/jquery-ui/jquery.ui.sortable.min.js']
        }
    },
    "font-awesome": {
        "css": {
            'dev': 'website/vendor/font-awesome/css/font-awesome.css',
            'production': 'website/vendor/font-awesome/css/font-awesome.min.css',
        }
    },
    "timepicker": {
        "css": {
            'dev': 'website/vendor/bootstrap-timepicker/css/bootstrap-timepicker.css',
            'production': 'website/vendor/bootstrap-timepicker/css/bootstrap-timepicker.min.css',
        },
        "js": {
            'dev': 'website/vendor/bootstrap-timepicker/js/bootstrap-timepicker.js',
            'production': 'website/vendor/bootstrap-timepicker/js/bootstrap-timepicker.min.js',
        }
    },
    "datepicker": {
        "css": {
            'dev': 'website/vendor/bootstrap-datepicker/css/datepicker.css'
        },
        "js": {
            'dev': 'website/vendor/bootstrap-datepicker/js/bootstrap-datepicker.js',
        }
    },
    "flot": {
        "js": {
            'dev': ['website/vendor/flot/jquery.flot.js', 'website/vendor/flot/jquery.flot.pie.js',
                    'website/vendor/flot/jquery.flot.time.js',
                    'website/vendor/flot/jquery.flot.resize.js', 'website/vendor/flot/jquery.flot.aggregate.js',
                    'website/vendor/flot/jquery.flot.categories.js']
        }
    },
    "image-gallery": {
        "css": {
            'dev': 'website/vendor/bootstrap-image-gallery/css/bootstrap-image-gallery.css',
            'production': 'website/vendor/bootstrap-image-gallery/css/bootstrap-image-gallery.css',
        },
        "js": {
            'dev': ['website/vendor/load-image/load-image.js',
                    'website/vendor/bootstrap-image-gallery/js/bootstrap-image-gallery.js'],
            'production': ['website/vendor/load-image/load-image.min.js',
                           'website/vendor/bootstrap-image-gallery/js/bootstrap-image-gallery.js']
        }
    },
    "select": {
        "css": {
            'dev': ['website/vendor/select2/select2.css', 'website/vendor/selectize/selectize.css',
                    'website/vendor/selectize/selectize.bootstrap3.css'],
        },
        "js": {
            'dev': ['website/vendor/selectize/selectize.js', 'website/vendor/select2/select2.js'],
            'production': ['website/vendor/selectize/selectize.min.js', 'website/vendor/select2/select2.min.js']
        }
    },
    "multiselect": {
        "css": {
            'dev': 'website/vendor/bootstrap-multiselect/css/bootstrap-multiselect.css',
        },
        "js": {
            'dev': 'website/vendor/bootstrap-multiselect/js/bootstrap-multiselect.js',
        }
    },
    "snapjs": {
        "css": {
            'dev': 'website/vendor/snapjs/snap.css',
        },
        "js": {
            'dev': 'website/vendor/snapjs/snap.js',
        }
    },
    'ckeditor': {
        'js': 'website/vendor/common/ckeditor/ckeditor.js',
        'css': 'contents.css'
    }
}