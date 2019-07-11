from django.utils.module_loading import import_module


class StrBeCode:
    @classmethod
    def path_to_class(cls, path):
        path = path.split('.')
        module = import_module('.'.join(path[0: -1]))
        return getattr(module, path[-1])

    # @classmethod
    #
