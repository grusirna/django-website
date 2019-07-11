from django.conf import settings
from website.tools.aop import StrBeCode


class DbConf:
    def __init__(self):
        self.db_conf_model_class = StrBeCode.path_to_class(getattr(settings, 'DB_CONF_MODEL', ''))

    def get_conf_item(self, key):
        return self.db_conf_model_class.objects.get_item(key)

    def set_conf_item(self, key):
        self.db_conf_model_class.objects.set_item(key)


db_conf = DbConf()

if __name__ == "__main__":
    print(db_conf.get_conf_model())
