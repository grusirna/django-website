import datetime

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.template.loader import get_template
from django.utils import timezone
from django.utils.encoding import smart_str
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.utils.translation import ugettext_lazy as _

from website.views.configs import EMPTY_CHANGELIST_VALUE, FILTER_PREFIX
from website.tools.dutils import RelatedObject, get_cache
from website.views.utils import get_model_from_relation, reverse_field_path, get_limit_choices_to_from_path, \
    prepare_lookup_value


class FieldFilterManager(object):
    _field_list_filters = []
    _take_priority_index = 0

    def register(self, list_filter_class, take_priority=False):
        if take_priority:
            # 是否优先使用
            self._field_list_filters.insert(
                self._take_priority_index, list_filter_class)
            self._take_priority_index += 1
        else:
            self._field_list_filters.append(list_filter_class)
        return list_filter_class

    def create(self, field, request, params, model, view, field_path):
        for list_filter_class in self._field_list_filters:
            if not list_filter_class.test(field, request, params, model, view, field_path):
                continue
            return list_filter_class(field, request, params, model, view, field_path=field_path)


manager = FieldFilterManager()


class BaseFilter(object):
    '''
    过滤器基类
    '''
    title = None  # 过滤器显示名
    template = 'website/filters/list.tpl'  # 过滤器使用的模板
    parameter_name = None  # 过滤器名    主key

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        '''
        用于判断是否应用该过滤器
        '''
        pass

    def __init__(self, request, params, model, view):
        self.used_params = {}  # 当前请求使用了的参数数据 eg: {'tee_date__gte': 'xxx'} {'slug__contains'='d9c98cb5'}
        self.request = request  # 当前请求对象
        self.params = params  # 当前请求的所有参数数据
        self.model = model  # 表模型，当宿主为 ListViewTemplate 时 model 为空
        self.view = view  # 当前页面主体对象
        # 确保子类设置了 title 成员
        if self.title is None:
            raise ImproperlyConfigured(+
                                       "The filter '%s' does not specify "
                                       "a 'title'." % self.__class__.__name__)

    def query_string(self, new_params=None, remove=None):
        '''
        根据参数生成？ url  eg：?_p_guarantee_date__gte=2016-01-05&_p_guarantee_date__lt=2016-01-14
        '''
        return self.view.get_query_string(new_params, remove)

    def form_params(self):
        '''
        生成 url 参数信息的 hidden input
        '''
        return self.view.get_form_params(
            remove=[FILTER_PREFIX + k for k in list(self.used_params.keys())])

    def has_output(self):
        '''
        过滤器是否有choices选项    必须重载
        '''
        raise NotImplementedError

    @property
    def is_used(self):
        '''
        是否使用了此过滤器
        '''
        return len(self.used_params) > 0

    def do_filte(self, queryset):
        """
        执行过滤器查询 需返回queryset   必须重载
        """
        raise NotImplementedError

    def get_context(self):
        return {'title': self.title, 'spec': self, 'form_params': self.form_params()}

    def __str__(self):
        tpl = get_template(self.template)
        return mark_safe(tpl.render(context=self.get_context()))


class InputFilter(BaseFilter):
    lookup_formats = {}  # 过滤器涉及的子类型和url参数之间映射字典

    def __init__(self, request, params, model, view):
        super(InputFilter, self).__init__(request, params, model, view)
        # 确保子类设置了 lookup_formats 成员
        if self.lookup_formats is None:
            raise ImproperlyConfigured(
                "The filter '%s' does not specify "
                "a 'lookup_formats'." % self.__class__.__name__)

        # 设置 self.lookup_[key] = value，和 self.context_params、self.used_params
        self.context_params = {}  # 传给模板的context变量
        for name, format in list(self.lookup_formats.items()):
            p = format % self.parameter_name
            self.context_params["%s_name" % name] = FILTER_PREFIX + p
            if p in params:
                value = prepare_lookup_value(p, params.pop(p))
                self.used_params[p] = value
                self.context_params["%s_val" % name] = value
            else:
                self.context_params["%s_val" % name] = ''

        list([setattr(self, 'lookup_' + kv[0], kv[1]) for kv in list(self.context_params.items())])

    def has_output(self):
        return True

    def get_context(self):
        context = super(InputFilter, self).get_context()
        context.update(self.context_params)
        context['remove_url'] = self.query_string({}, [FILTER_PREFIX + k for k in list(self.used_params.keys())])
        return context

    def get_value(self, name):
        _param_name = self.lookup_formats[name] % self.parameter_name
        return self.used_params.get(_param_name, None)


class FieldFilter(InputFilter):
    '''
    模型字段过滤器基类
    '''

    def __init__(self, field, request, params, model, view, field_path):
        # 多了首尾两个参数    字段类 和 字段名
        self.field = field
        self.field_path = field_path
        self.parameter_name = field_path

        self.title = getattr(field, 'verbose_name', field_path)
        self.context_params = {}

        super(FieldFilter, self).__init__(request, params, model, view)

    def do_filte(self, queryset):
        '''根据 used_params 做查询'''
        return queryset.filter(**self.used_params)


class ListFieldFilter(FieldFilter):
    '''
    列表型字段过滤器基类
    '''
    template = 'website/filters/list.tpl'

    def get_context(self):
        context = super(ListFieldFilter, self).get_context()
        context['choices'] = list(self.choices())
        return context


class ChoicesBaseFilter(BaseFilter):
    def __init__(self, request, params, model, view):
        super(ChoicesBaseFilter, self).__init__(request, params, model, view)

        lookup_choices = self.lookups(request, view)
        if lookup_choices is None:
            lookup_choices = ()
        self.lookup_choices = list(lookup_choices)
        if self.parameter_name in params:
            value = params.pop(self.parameter_name)
            self.used_params[self.parameter_name] = value

    def lookups(self, request, view):
        '''配置选项 eg [ ('1', '上个月'), ('2', '下个月') ]'''
        raise NotImplementedError

    def choices(self):
        yield {
            'selected': self.value() is None,
            'query_string': self.query_string({}, ['_p_' + self.parameter_name]),
            'display': _('All'),
        }
        for lookup, title in self.lookup_choices:
            yield {
                'selected': self.value() == lookup,
                'query_string': self.query_string({'_p_' + self.parameter_name: lookup, }, []),
                'display': title,
            }

    def get_context(self):
        context = super(ChoicesBaseFilter, self).get_context()
        context['choices'] = list(self.choices())
        return context

    def has_output(self):
        return len(self.lookup_choices) > 0

    def value(self):
        return self.used_params.get(self.parameter_name, None)


class TextBaseFilter(InputFilter):
    template = 'website/filters/char.tpl'
    lookup_formats = {'in': '%s__in', 'search': '%s__contains'}

    def value(self):
        '''获取Text的值'''
        return self.get_value('search')


class NumberBaseFilter(InputFilter):
    template = 'website/filters/number.tpl'
    lookup_formats = {'equal': '%s__exact', 'lt': '%s__lt', 'gt': '%s__gt',
                      'ne': '%s__ne', 'lte': '%s__lte', 'gte': '%s__gte',
                      }


class DateBaseFilter(ChoicesBaseFilter, InputFilter):
    template = 'website/filters/date_base.tpl'
    lookup_formats = {'since': '%s__gte', 'until': '%s__lt'}

    def __init__(self, request, params, model, view):
        # date_params 包含 FILTER_PREFIX 的 used_params
        self.field_generic = '%s__' % self.parameter_name
        self.date_params = dict([(FILTER_PREFIX + k, v) for k, v in list(params.items())
                                 if k.startswith(self.field_generic)])

        super(DateBaseFilter, self).__init__(request, params, model, view)

    def lookups(self, request, view):
        now = timezone.now()
        if now.tzinfo is not None:
            current_tz = timezone.get_current_timezone()
            now = now.astimezone(current_tz)
            if hasattr(current_tz, 'normalize'):
                now = current_tz.normalize(now)

        today = now.date()  # now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + datetime.timedelta(days=1)
        return (
            (_('全部'), {}),
            (_('Today'), {
                self.lookup_since_name: str(today),
                self.lookup_until_name: str(tomorrow),
            }),
        )

    def choices(self):
        for title, param_dict in self.lookups(self.request, self.view):
            yield {
                'selected': self.date_params == param_dict,
                'query_string': self.query_string(
                    param_dict, [FILTER_PREFIX + self.field_generic]),
                'display': title,
            }


@manager.register
class BooleanFieldListFilter(ListFieldFilter):
    lookup_formats = {'exact': '%s__exact', 'isnull': '%s__isnull'}

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return isinstance(field, (models.BooleanField, models.NullBooleanField))

    def choices(self):
        for lookup, title in (('', _('All')), ('1', _('Yes')), ('0', _('No'))):
            yield {
                'selected': self.lookup_exact_val == lookup and not self.lookup_isnull_val,
                'query_string': self.query_string({
                    self.lookup_exact_name: lookup,
                }, [self.lookup_isnull_name]),
                'display': title,
            }
        if isinstance(self.field, models.NullBooleanField):
            yield {
                'selected': self.lookup_isnull_val == 'True',
                'query_string': self.query_string({
                    self.lookup_isnull_name: 'True',
                }, [self.lookup_exact_name]),
                'display': _('Unknown'),
            }


@manager.register
class ChoicesFieldListFilter(ListFieldFilter):
    lookup_formats = {'exact': '%s__exact'}

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return bool(field.choices)

    def choices(self):
        yield {
            'selected': self.lookup_exact_val is '',
            'query_string': self.query_string({}, [self.lookup_exact_name]),
            'display': _('All')
        }
        for lookup, title in self.field.flatchoices:
            yield {
                'selected': smart_str(lookup) == self.lookup_exact_val,
                'query_string': self.query_string({self.lookup_exact_name: lookup}),
                'display': title,
            }


@manager.register
class TextFieldListFilter(FieldFilter):
    template = 'website/filters/char.tpl'
    lookup_formats = {'in': '%s__in', 'search': '%s__contains'}

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return isinstance(field, models.CharField) or isinstance(field, models.TextField)


@manager.register
class NumberFieldListFilter(FieldFilter):
    template = 'website/filters/number.tpl'
    lookup_formats = {'equal': '%s__exact', 'lt': '%s__lt', 'gt': '%s__gt',
                      'ne': '%s__ne', 'lte': '%s__lte', 'gte': '%s__gte',
                      }

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return isinstance(field, (models.DecimalField, models.FloatField, models.IntegerField))

    def do_filte(self, queryset):
        params = self.used_params.copy()
        ne_key = '%s__ne' % self.field_path
        if ne_key in params:
            queryset = queryset.exclude(
                **{self.field_path: params.pop(ne_key)})
        return queryset.filter(**params)


@manager.register
class DateFieldListFilter(ListFieldFilter):
    template = 'website/filters/date.tpl'
    lookup_formats = {'since': '%s__gte', 'until': '%s__lt',
                      'year': '%s__year', 'month': '%s__month', 'day': '%s__day',
                      'isnull': '%s__isnull'}

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return isinstance(field, models.DateField)

    def __init__(self, field, request, params, model, view, field_path):
        self.field_generic = '%s__' % field_path
        self.date_params = dict([(FILTER_PREFIX + k, v) for k, v in list(params.items())
                                 if k.startswith(self.field_generic)])

        super(DateFieldListFilter, self).__init__(field, request, params, model, view, field_path)

        now = timezone.now()
        if now.tzinfo is not None:
            current_tz = timezone.get_current_timezone()
            now = now.astimezone(current_tz)
            if hasattr(current_tz, 'normalize'):
                now = current_tz.normalize(now)

        if isinstance(field, models.DateTimeField):
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:  # field is a models.DateField
            today = now.date()
        tomorrow = today + datetime.timedelta(days=1)

        self.links = (
            (_('Any date'), {}),
            (_('Has date'), {
                self.lookup_isnull_name: False
            }),
            (_('Has no date'), {
                self.lookup_isnull_name: 'True'
            }),
            (_('Today'), {
                self.lookup_since_name: str(today),
                self.lookup_until_name: str(tomorrow),
            }),
            (_('Past 7 days'), {
                self.lookup_since_name: str(today - datetime.timedelta(days=7)),
                self.lookup_until_name: str(tomorrow),
            }),
            (_('This month'), {
                self.lookup_since_name: str(today.replace(day=1)),
                self.lookup_until_name: str(tomorrow),
            }),
            (_('This year'), {
                self.lookup_since_name: str(today.replace(month=1, day=1)),
                self.lookup_until_name: str(tomorrow),
            }),
        )

    def get_context(self):
        context = super(DateFieldListFilter, self).get_context()
        context['choice_selected'] = bool(self.lookup_year_val) or bool(self.lookup_month_val) \
                                     or bool(self.lookup_day_val)
        return context

    def choices(self):
        for title, param_dict in self.links:
            yield {
                'selected': self.date_params == param_dict,
                'query_string': self.query_string(
                    param_dict, [FILTER_PREFIX + self.field_generic]),
                'display': title,
            }


@manager.register
class RelatedFieldSearchFilter(FieldFilter):
    template = 'website/filters/fk_search.tpl'

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        if not (hasattr(field, 'remote_field') and bool(field.remote_field) or isinstance(field, RelatedObject)):
            return False
        related_modeladmin = view.website.modelconfigs.get(
            get_model_from_relation(field))
        return related_modeladmin and getattr(related_modeladmin, 'relfield_style', None) == 'fk-ajax'

    def __init__(self, field, request, params, model, model_admin, field_path):
        other_model = get_model_from_relation(field)
        if getattr(field, 'remote_field', False):
            rel_name = field.remote_field.name
        else:
            rel_name = other_model._meta.pk.name

        self.lookup_formats = {'in': '%%s__%s__in' % rel_name, 'exact': '%%s__%s__exact' % rel_name}
        super(RelatedFieldSearchFilter, self).__init__(
            field, request, params, model, model_admin, field_path)

        if hasattr(field, 'verbose_name'):
            self.lookup_title = field.verbose_name
        else:
            self.lookup_title = other_model._meta.verbose_name
        self.title = self.lookup_title
        self.search_url = model_admin.get_site_url('%s_%s_changelist' % (
            other_model._meta.app_label, other_model._meta.model_name))
        self.label = self.label_for_value(other_model, rel_name, self.lookup_exact_val) if self.lookup_exact_val else ""
        self.choices = '?'
        if field.remote_field.limit_choices_to:
            for i in list(field.remote_field.limit_choices_to):
                self.choices += "&_p_%s=%s" % (i, field.remote_field.limit_choices_to[i])
            self.choices = format_html(self.choices)

    def label_for_value(self, other_model, rel_name, value):
        try:
            obj = other_model._default_manager.get(**{rel_name: value})
            return '%s' % escape(Truncator(obj).words(14, truncate='...'))
        except (ValueError, other_model.DoesNotExist):
            return ""

    def get_context(self):
        context = super(RelatedFieldSearchFilter, self).get_context()
        context['search_url'] = self.search_url
        context['label'] = self.label
        context['choices'] = self.choices
        return context


@manager.register
class RelatedFieldListFilter(ListFieldFilter):
    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return (hasattr(field, 'remote_field') and bool(field.remote_field) or isinstance(field, RelatedObject))

    def __init__(self, field, request, params, model, model_admin, field_path):
        other_model = get_model_from_relation(field)
        if getattr(field, 'remote_field', False):
            rel_name = field.remote_field.name
        else:
            rel_name = other_model._meta.pk.name

        self.lookup_formats = {'in': '%%s__%s__in' % rel_name, 'exact': '%%s__%s__exact' %
                                                                        rel_name, 'isnull': '%s__isnull'}
        self.lookup_choices = field.get_choices(include_blank=False)
        # print('lookup_choices:', self.lookup_choices)
        # print('field:', field)
        super(RelatedFieldListFilter, self).__init__(
            field, request, params, model, model_admin, field_path)

        if hasattr(field, 'verbose_name'):
            self.lookup_title = field.verbose_name
        else:
            self.lookup_title = other_model._meta.verbose_name
        self.title = self.lookup_title

    def check_null(self):
        if hasattr(self.field, 'field'):
            _field = self.field.field
        else:
            _field = self.field
        ret = (isinstance(self.field, RelatedObject)
               and _field.null or hasattr(self.field, 'remote_field')
               and self.field.null)
        return ret

    def has_output(self):
        if self.check_null():
            extra = 1
        else:
            extra = 0
        return len(self.lookup_choices) + extra >= 1

    def expected_parameters(self):
        return [self.lookup_kwarg, self.lookup_kwarg_isnull]

    def choices(self):
        yield {
            'selected': self.lookup_exact_val == '' and not self.lookup_isnull_val,
            'query_string': self.query_string({},
                                              [self.lookup_exact_name, self.lookup_isnull_name]),
            'display': _('All'),
        }
        for pk_val, val in self.lookup_choices:
            yield {
                'selected': self.lookup_exact_val == smart_str(pk_val),
                'query_string': self.query_string({
                    self.lookup_exact_name: pk_val,
                }, [self.lookup_isnull_name]),
                'display': val,
            }
        if self.check_null():
            yield {
                'selected': bool(self.lookup_isnull_val),
                'query_string': self.query_string({
                    self.lookup_isnull_name: 'True',
                }, [self.lookup_exact_name]),
                'display': EMPTY_CHANGELIST_VALUE,
            }


@manager.register
class CommonFieldListFilter(FieldFilter):
    template = 'website/filters/common.tpl'
    lookup_formats = {'equal': '%s__exact',
                      'ne': '%s__ne',
                      'search': '%s__contains'
                      }

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return True

    def do_filte(self, queryset):
        params = self.used_params.copy()
        ne_key = '%s__ne' % self.field_path
        if ne_key in params:
            queryset = queryset.exclude(
                **{self.field_path: params.pop(ne_key)})
        return queryset.filter(**params)


@manager.register
class MultiSelectFieldListFilter(ListFieldFilter):
    """ Delegates the filter to the default filter and ors the results of each

    Lists the distinct values of each field as a checkbox
    Uses the default spec for each

    """
    template = 'website/filters/checklist.tpl'
    lookup_formats = {'in': '%s__in'}
    cache_config = {'enabled': False, 'key': 'quickfilter_%s', 'timeout': 3600, 'cache': 'default'}

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return True

    def get_cached_choices(self):
        if not self.cache_config['enabled']:
            return None
        c = get_cache(self.cache_config['cache'])
        return c.get(self.cache_config['key'] % self.field_path)

    def set_cached_choices(self, choices):
        if not self.cache_config['enabled']:
            return
        c = get_cache(self.cache_config['cache'])
        return c.set(self.cache_config['key'] % self.field_path, choices)

    def __init__(self, field, request, params, model, model_admin, field_path, field_order_by=None, field_limit=None,
                 sort_key=None, cache_config=None):
        super(MultiSelectFieldListFilter, self).__init__(field, request, params, model, model_admin, field_path)

        # Check for it in the cachce
        if cache_config is not None and type(cache_config) == dict:
            self.cache_config.update(cache_config)

        if self.cache_config['enabled']:
            self.field_path = field_path
            choices = self.get_cached_choices()
            if choices:
                self.lookup_choices = choices
                return

        # Else rebuild it
        queryset = self.view.queryset().exclude(**{"%s__isnull" % field_path: True}).values_list(field_path,
                                                                                                 flat=True).distinct()
        # queryset = self.view.queryset().distinct(field_path).exclude(**{"%s__isnull"%field_path:True})

        if field_order_by is not None:
            # Do a subquery to order the distinct set
            queryset = self.view.queryset().filter(id__in=queryset).order_by(field_order_by)

        if field_limit is not None and type(field_limit) == int and queryset.count() > field_limit:
            queryset = queryset[:field_limit]

        self.lookup_choices = [str(it) for it in queryset.values_list(field_path, flat=True) if str(it).strip() != ""]
        if sort_key is not None:
            self.lookup_choices = sorted(self.lookup_choices, key=sort_key)

        if self.cache_config['enabled']:
            self.set_cached_choices(self.lookup_choices)

    def choices(self):
        self.lookup_in_val = (type(self.lookup_in_val) in (tuple, list)) and self.lookup_in_val or list(
            self.lookup_in_val)
        yield {
            'selected': len(self.lookup_in_val) == 0,
            'query_string': self.query_string({}, [self.lookup_in_name]),
            'display': _('All'),
        }
        for val in self.lookup_choices:
            yield {
                'selected': smart_str(val) in self.lookup_in_val,
                'query_string': self.query_string({self.lookup_in_name: ",".join([val] + self.lookup_in_val), }),
                'remove_query_string': self.query_string(
                    {self.lookup_in_name: ",".join([v for v in self.lookup_in_val if v != val]), }),
                'display': val,
            }


@manager.register
class AllValuesFieldListFilter(ListFieldFilter):
    lookup_formats = {'exact': '%s__exact', 'isnull': '%s__isnull'}

    @classmethod
    def test(cls, field, request, params, model, view, field_path):
        return True

    def __init__(self, field, request, params, model, view, field_path):
        parent_model, reverse_path = reverse_field_path(model, field_path)
        queryset = parent_model._default_manager.all()
        # optional feature: limit choices website on existing relationships
        # queryset = queryset.complex_filter(
        #    {'%s__isnull' % reverse_path: False})
        limit_choices_to = get_limit_choices_to_from_path(model, field_path)
        queryset = queryset.filter(limit_choices_to)

        self.lookup_choices = (queryset
                               .distinct()
                               .order_by(field.name)
                               .values_list(field.name, flat=True))
        super(AllValuesFieldListFilter, self).__init__(
            field, request, params, model, view, field_path)

    def choices(self):
        yield {
            'selected': (self.lookup_exact_val is '' and self.lookup_isnull_val is ''),
            'query_string': self.query_string({}, [self.lookup_exact_name, self.lookup_isnull_name]),
            'display': _('All'),
        }
        include_none = False
        for val in self.lookup_choices:
            if val is None:
                include_none = True
                continue
            val = smart_str(val)
            yield {
                'selected': self.lookup_exact_val == val,
                'query_string': self.query_string({self.lookup_exact_name: val},
                                                  [self.lookup_isnull_name]),
                'display': val,
            }
        if include_none:
            yield {
                'selected': bool(self.lookup_isnull_val),
                'query_string': self.query_string({self.lookup_isnull_name: 'True'},
                                                  [self.lookup_exact_name]),
                'display': EMPTY_CHANGELIST_VALUE,
            }


@manager.register
class QuickFilterMultiSelectFieldListFilter(MultiSelectFieldListFilter):
    """ Delegates the filter to the default filter and ors the results of each
    Lists the distinct values of each field as a checkbox
    Uses the default spec for each
    """
    template = 'website/filters/quickfilter.tpl'
