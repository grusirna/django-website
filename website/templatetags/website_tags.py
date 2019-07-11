from django.template import Library
from django.utils.safestring import mark_safe
from django.conf import settings
from website.views.utils import static, vendor as util_vendor

register = Library()


@register.simple_tag(takes_context=True)
def plugin_block(context, block_name, *args, **kwargs):
    '''
    后台block实现
    '''
    if 'cl' not in context:
        return ""

    view = context['cl']
    nodes = []
    method_name = 'block_%s' % block_name

    for view in [view] + view.plugins:
        if hasattr(view, method_name) and callable(getattr(view, method_name)):
            block_func = getattr(view, method_name)
            result = block_func(context, nodes, *args, **kwargs)
            if result and type(result) in (str, str):
                nodes.append(result)
    if nodes:
        return mark_safe(''.join(nodes))
    else:
        return ""


@register.filter
def admin_urlname(value, arg):
    print(locals())
    return 'namespace:%s_%s_%s' % (value.app_label, value.model_name, arg)


@register.filter
def append_namespace(value, website):
    print(locals())

    i = value.find(':')
    s = value[i:]
    return website.namespace + s


@register.filter
def website_namespace(value, arg):
    return '%s:%s' % (value.namespace, arg)


static = register.simple_tag(static)


@register.simple_tag(takes_context=True)
def vendor(context, *tags):
    return util_vendor(*tags).render()


@register.filter
def get_item(container, key):
    if isinstance(container, dict):
        try:
            value = container.get(key)
        except (KeyError, TypeError):
            value = settings.TEMPLATE_STRING_IF_INVALID
    elif isinstance(container, (list, tuple)):
        try:
            value = container[key]
        except (IndexError, TypeError):
            value = settings.TEMPLATE_STRING_IF_INVALID
    else:
        value = settings.TEMPLATE_STRING_IF_INVALID
    return value
