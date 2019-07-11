from django.apps import AppConfig


class BaseConfig(AppConfig):
    name = 'website'
    verbose_name = '管理员'

    def ready(self):
        # autodiscover()
        pass
