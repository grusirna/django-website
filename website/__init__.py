VERSION = [0, 1, 0]

# django patch
from django.db.models.options import Options


def get_all_related_objects(self):
    return [
        f for f in self.get_fields()
        if (f.one_to_many or f.one_to_one)
           and f.auto_created and not f.concrete
    ]


Options.get_all_related_objects = get_all_related_objects


def get_all_related_many_to_many_objects(self):
    return [
        f for f in self.get_fields(include_hidden=True)
        if f.many_to_many and f.auto_created
    ]


Options.get_all_related_many_to_many_objects = get_all_related_many_to_many_objects


def get_field_by_name(self, name):
    return [self.get_field(name)]


Options.get_field_by_name = get_field_by_name

default_module_config = 'website.__mod__.BaseConfig'
