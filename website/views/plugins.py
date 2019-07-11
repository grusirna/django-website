import copy
import datetime
import io
import json
import operator
import re
import urllib.parse
from functools import reduce

import django.contrib
from django import forms
from django.contrib.contenttypes.models import ContentType
from crispy_forms.layout import Field, Column, Layout
from website.models import Viewmark, UserSetting
from website.tools import dutils
from website.tools.dutils import render_to_string, JsonErrorDict, RelatedObject
from website.tools.storage import get_storage
from website.tools.types import SortedDict
from website.views.configs import ACTION_CHECKBOX_NAME, COL_LIST_VAR, ORDER_VAR, SEARCH_VAR, FILTER_PREFIX, \
    RELATE_PREFIX, ALL_VAR, EXPORT_MAX
from website.views.fields import AdminImageField, InlineShowField, Inline, InlineFormset, \
    ModelTreeChoiceField, ModelTreeChoiceFieldFK, ModelTreeChoiceFieldFKLeaf, Fieldset
from website.views.fieldsets import Container
from website.views.filters import manager as filter_manager, DateFieldListFilter, DateBaseFilter, \
    RelatedFieldSearchFilter, QuickFilterMultiSelectFieldListFilter
from website.views.utils import model_format_dict, display_for_field, label_for_field, get_fields_from_path, \
    lookup_needs_distinct, get_model_from_relation
from website.views.views import ViewUtilMixin, ListViewTemplate, ActionViewTemplate, \
    BatchDeletionViewTemplate, \
    ModelFormViewTemplate, GenericInlineModelView, InlineFormViewTemplate, DetailView, DetailViewMixin, StepsHelper, \
    ListRow, \
    ListCell
from website.views.forms import ManagementForm
from website.views.widgets import RelatedFieldWidgetWrapper, ImageWidget
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist, SuspiciousOperation, ValidationError, ImproperlyConfigured
from django.db import models
from django.db.models import Min, Max, Avg, Sum, Count, Q, BooleanField, NullBooleanField, ManyToManyField, TextField, \
    ForeignKey
from django.db.models.constants import LOOKUP_SEP
from django.forms import all_valid, modelform_factory, Media
from django.http import HttpResponse, HttpResponseRedirect
from django.template import RequestContext, loader
from django.templatetags.static import static
from django.urls import reverse, NoReverseMatch
from django.utils.encoding import force_str, smart_str
from django.utils.html import escape
from django.utils.text import capfirst
from django.utils.translation import ungettext, ugettext as _, ugettext_lazy as _
from django.utils.safestring import mark_safe
from django.utils.xmlutils import SimplerXMLGenerator


class ViewPlugin(ViewUtilMixin):

    def __init__(self, view):
        self.view = view
        self.website = view.website
        try:
            self.model = view.model
            self.opts = view.model._meta
        except Exception:
            self.model = None
            self.opts = None

    def init_request(self, *args, **kwargs):
        return self.__class__.__name__ not in self.view.exclude_plugins

QUERY_TERMS = {
    'exact', 'iexact', 'contains', 'icontains', 'gt', 'gte', 'lt', 'lte', 'in',
    'startswith', 'istartswith', 'endswith', 'iendswith', 'range', 'year',
    'month', 'day', 'week_day', 'hour', 'minute', 'second', 'isnull', 'search',
    'regex', 'iregex',
}
# <editor-fold desc="多选插件">
checkbox_form_field = forms.CheckboxInput({'class': 'action-select'}, lambda value: False)


def action_checkbox(obj):
    if type(obj) == dict:
        _pk = obj['_pk']
    else:
        _pk = obj.pk
    return checkbox_form_field.render(ACTION_CHECKBOX_NAME, force_str(_pk))


action_checkbox.verbose_name = mark_safe(
    '<input type="checkbox" id="action-toggle" />')
action_checkbox.allow_tags = True
action_checkbox.allow_export = False
action_checkbox.is_column = False


class ActionPlugin(ViewPlugin):
    # 配置项目
    actions = []
    can_select_all = True
    can_select = False
    can_delete_multi = True

    def init_request(self, *args, **kwargs):
        self.actions = self._get_actions()
        return self.view.can_select

    def get_list_display(self, list_display):
        list_display.insert(0, 'action_checkbox')
        self.view.action_checkbox = action_checkbox
        return list_display

    def get_list_display_links(self, list_display_links):
        if len(list_display_links) == 1 and list_display_links[0] == 'action_checkbox':
            return list(self.view.list_display[1:2])
        return list_display_links

    def _get_action_choices(self):
        choices = []
        if type(self.actions) == SortedDict:
            show_action = []
            if hasattr(self.view, 'action_show_by_status'):
                for each_act in self.view.action_always_show:
                    show_action.append("act_{}".format(each_act))

            if hasattr(self.view, 'action_show_by_status'):
                for status, value_action in self.view.action_show_by_status.iteritems():
                    if value_action.get(self.request.GET.get(status, None)):
                        for act in value_action.get(self.request.GET.get(status, None)):
                            show_action.append("act_{}".format(act))

            for ac, name, verbose_name, icon in list(self.actions.values()):
                if self.opts:
                    choice = (name, verbose_name % model_format_dict(self.opts), icon)
                else:
                    choice = (name, verbose_name, icon)

                if hasattr(self.view, 'action_show_by_status'):
                    if not name.startswith('act_'):
                        choices.append(choice)
                    elif name in show_action:
                        choices.append(choice)
                else:
                    choices.append(choice)
        else:
            for ac in self.actions:
                ac_url = ac.get_block_url()
                choices.append((ac_url + '?', ac.verbose_name, ac.icon))
        return choices

    def get_context(self, context):
        if self.view.result_count:
            av = self.view
            selection_note_all = ungettext('%(total_count)s selected', 'All %(total_count)s selected', av.result_count)
            m_action_choices = self._get_action_choices()
            new_context = {
                'selection_note': _('0 of %(cnt)s selected') % {'cnt': len(av.result_list)},
                'selection_note_all': selection_note_all % {'total_count': av.result_count},
                'action_choices': m_action_choices[:3],
                'action_choices_more': len(m_action_choices) > 3 and m_action_choices[3:] or [],
            }
            context.update(new_context)
        return context

    def post_response(self, response, *args, **kwargs):
        request = self.view.request
        av = self.view

        # Actions with no confirmation
        if self.actions and 'action' in request.POST:
            action = request.POST['action']
            if action not in self.actions:
                msg = '非法操作'
                av.message_user(msg)
            else:
                ac, name, description, icon = self.actions[action]
                # 是否为选择所有
                select_across = request.POST.get('select_across', False) == '1'
                selected = request.POST.getlist(ACTION_CHECKBOX_NAME)

                if not selected and not select_across:
                    msg = '请先选择'
                    av.message_user(msg)
                else:
                    queryset = av.list_queryset._clone()
                    if not select_across:
                        queryset = av.list_queryset.filter(pk__in=selected)

                    ret = self._response_action(ac, queryset)
                    if isinstance(ret, str):
                        self.message_user(ret, 'error')
                    if isinstance(ret, HttpResponse):
                        return ret
                    else:
                        return HttpResponseRedirect(self.action_view.get_redirect_url())
        return response

    def _response_action(self, ac, queryset):
        if isinstance(ac, type) and issubclass(ac, ActionViewTemplate):
            action_view = self.getmodelviewclass(ac, self.view.model)
            self.action_view = action_view
            action_view.init_action(self.view)
            return action_view.do_action(queryset)
        else:
            return ac(self.view, self.request, queryset)

    def _get_actions(self):
        '''获取所有action'''
        if not self.view.opts:
            actions = self.actions or self.view.form_actions
            return [ac for ac in actions if not ac.perm or (ac.perm and self.user.has_perm('auth.' + ac.perm))]

        if self.actions is None:
            return SortedDict()
        if self.model and self.view.grid and self.can_delete_multi:
            actions = [self._get_action(action) for action in [BatchDeletionViewTemplate]]
        else:
            actions = []

        for klass in self.view.__class__.mro()[::-1]:
            class_actions = getattr(klass, 'actions', [])
            if not class_actions:
                continue
            actions.extend(
                [self._get_action(action) for action in class_actions])

        actions = [_f for _f in actions if _f]
        actions = SortedDict([
            (name, (ac, name, desc, icon))
            for ac, name, desc, icon in actions
        ])

        return actions

    def _get_action(self, action):
        '''获取指定action的信息'''
        if isinstance(action, type) and issubclass(action, ActionViewTemplate):
            if not action.has_perm(self.view):
                return None
            return (
                action,
                getattr(action, 'action_name') or 'act_%s' % action.__name__,
                getattr(action, 'verbose_name') or action.__name__,
                getattr(action, 'icon')
            )
        # 对函数型action的支持
        elif callable(action):
            func = action
            action = action.__name__
        elif hasattr(self.view.__class__, action):
            func = getattr(self.view.__class__, action)
        else:
            return None
        if hasattr(func, 'verbose_name'):
            description = func.verbose_name
        else:
            description = action
        return func, action, description, getattr(func, 'icon', 'tasks')

    def makeheader(self, item, field_name, row):
        if item.attr and field_name == 'action_checkbox':
            item.classes.append("action-checkbox-column")
        return item

    def makecell(self, item, obj, field_name, row):
        if item.field is None and field_name == 'action_checkbox':
            item.classes.append("action-checkbox")
        return item

    def get_media(self, media):
        if self.view.result_count:
            media = media + self.vendor('website.plugin.actions.js', 'website.plugins.css')
        return media

    def block_results_bottom(self, context, nodes):
        if self.view.result_count:
            _tpl = 'website/blocks/grid.results_bottom.actions.tpl' if self.view.grid else 'website/blocks/form.results_bottom.actions.tpl'
            nodes.append(render_to_string(_tpl, context_instance=context))


# </editor-fold>

# <editor-fold desc="聚合插件">
AGGREGATE_METHODS = {
    'min': Min, 'max': Max, 'avg': Avg, 'sum': Sum, 'count': Count
}
AGGREGATE_TITLE = {
    'min': _('Min'), 'max': _('Max'), 'avg': _('Avg'), 'sum': _('Sum'), 'count': _('Count')
}


class AggregationPlugin(ViewPlugin):
    aggregate_fields = {}

    def init_request(self, *args, **kwargs):
        return bool(self.aggregate_fields)

    def _get_field_aggregate(self, field_name, obj, row):
        item = ListCell(field_name, row)
        item.classes = ['aggregate', ]
        if field_name not in self.aggregate_fields:
            item.text = ""
        else:
            try:
                f = self.opts.get_field(field_name)
                agg_method = self.aggregate_fields[field_name]
                key = '%s__%s' % (field_name, agg_method)
                if key not in obj:
                    item.text = ""
                else:
                    item.text = display_for_field(obj[key], f)
                    item.wraps.append(
                        '%%s<span class="aggregate_title label label-info">%s</span>' % AGGREGATE_TITLE[agg_method])
                    item.classes.append(agg_method)
            except FieldDoesNotExist:
                item.text = ""

        return item

    def _get_aggregate_row(self):
        queryset = self.view.list_queryset._clone()
        obj = queryset.aggregate(*[AGGREGATE_METHODS[method](field_name) for field_name, method in
                                   list(self.aggregate_fields.items()) if method in AGGREGATE_METHODS])

        row = ListRow()
        row['is_display_first'] = False
        row.cells = [self._get_field_aggregate(field_name, obj, row) for field_name in self.view.list_display]
        row.css_class = 'info aggregate'
        return row

    def results(self, rows):
        if rows:
            rows.append(self._get_aggregate_row())
        return rows

    # Media
    def get_media(self, media):

        return media + self.vendor('website.plugin.aggregation.css')


# </editor-fold>

# <editor-fold desc="ajax插件">
class AjaxPlugin(ViewPlugin):
    '''
    ajax后台处理基类
    '''

    def init_request(self, *args, **kwargs):
        return bool(self.request.is_ajax() or '_ajax' in self.param_list())


class AjaxListPlugin(AjaxPlugin):
    def get_list_display(self, list_display):
        list_fields = [field for field in self.request.GET.get('_fields', "").split(",")
                       if field.strip() != ""]
        if list_fields:
            return list_fields
        return list_display

    def get_result_list(self, response):
        av = self.view
        base_fields = self.get_list_display(av.base_list_display)
        headers = dict([(c.field_name, force_str(c.text)) for c in av.makeheaders(
        ).cells if c.field_name in base_fields])

        objects = [dict([(o.field_name, escape(str(o.value))) for i, o in
                         enumerate([c for c in r.cells if c.field_name in base_fields])])
                   for r in av.results()]

        return self.render_response(
            {'headers': headers, 'objects': objects, 'total_count': av.result_count, 'has_more': av.has_more})


class AjaxFormPlugin(AjaxPlugin):

    def post_response(self, __):
        new_obj = self.view.new_obj
        return self.render_response({
            'result': 'success',
            'obj_id': new_obj.pk,
            'obj_repr': str(new_obj),
            'change_url': self.view.model_admin_url('change', new_obj.pk),
            'detail_url': self.view.model_admin_url('detail', new_obj.pk)
        })

    def get_response(self, __):
        if self.request.method.lower() != 'post':
            return __()

        result = {}
        form = self.view.form_obj
        if form.is_valid():
            result['result'] = 'success'
        else:
            result['result'] = 'error'
            result['errors'] = JsonErrorDict(form.errors, form).as_json()

        return self.render_response(result)


class AjaxFormPagePlugin(AjaxPlugin):
    '''
    用于普通表单页
    '''

    def post_response(self, __):
        return self.render_response({
            'result': 'success',
        })

    def get_response(self, __):
        if self.request.method.lower() != 'post':
            return __()

        result = {}
        form = self.view.form_obj
        if form.is_valid():
            result['result'] = 'success'
        else:
            result['result'] = 'error'
            result['errors'] = JsonErrorDict(form.errors, form).as_json()

        return self.render_response(result)


class AjaxDetailPlugin(AjaxPlugin):
    def get_response(self, __):
        if self.request.GET.get('_format') == 'html':
            self.view.detail_template = 'website/views/quick_detail.tpl'
            return __()

        form = self.view.form_obj
        layout = form.helper.layout

        results = []

        for p, f in layout.get_field_names():
            result = self.view.get_field_result(f)
            results.append((result.label, result.val))

        return self.render_response(SortedDict(results))


# </editor-fold>

# <editor-fold desc="Model权限过滤器插件">
class ModelPermissionPlugin(ViewPlugin):
    '''
    控制只有对象所有者才能查看对象 影响范围: 列表视图、表单视图等用到queryset的地方
    '''

    user_can_access_owned_objects_only = False
    user_owned_objects_field = 'user'

    def queryset(self, qs):
        if self.user_can_access_owned_objects_only and \
                not self.user.is_superuser:
            filters = {self.user_owned_objects_field: self.user.id}
            qs = qs.filter(**filters)
        return qs


# </editor-fold>

# <editor-fold desc="用户相关插件">
class UserFieldPlugin(ViewPlugin):
    '''
    用户字段在表单中隐藏，默认填充为当前用户
    '''

    user_fields = []

    def get_field_attrs(self, __, db_field, **kwargs):
        if self.user_fields and db_field.name in self.user_fields:
            return {'widget': forms.HiddenInput}
        return __()

    def get_form_datas(self, datas):
        if self.user_fields and 'data' in datas:
            if hasattr(datas['data'], '_mutable') and not datas['data']._mutable:
                datas['data'] = datas['data'].copy()
            for f in self.user_fields:
                datas['data'][f] = self.user.id
        return datas


class ResetLinkPlugin(ViewPlugin):
    def block_form_bottom(self, context, nodes):
        reset_link = self.get_site_url('xadmin_password_reset')
        return '<div class="text-info" style="margin-top:15px;"><a href="%s"><i class="fa fa-question-sign"></i> %s</a></div>' % (
            reset_link, _('Forgotten your password or username?'))


class RegisterPlug(ViewPlugin):
    def init_request(self, *args, **kwargs):
        return True

    def block_form_bottom(self, context, nodes):
        url = self.get_site_url("register")
        return "<div class='text-info' style='margin-top:15px;'><a href='%s'>%s</a></div>" % (
            url, '注册')


class SocialLoginPlugin(ViewPlugin):
    def init_request(self, *args, **kwargs):
        return getattr(settings, 'XADMIN_SOCIAL_ENABLE', False)

    def get_media(self, media):
        media = media + self.vendor('website.plugins.social.css')
        return media

    def block_form_bottom(self, context, nodes):
        _tpl = 'website/auth/login_social_block.tpl'
        nodes.append(dutils.render_to_string(_tpl, context_instance=context))


class ViewmarkPlugin(ViewPlugin):
    list_viewmarks = []
    show_viewmarks = True

    def init_request(self, *args, **kwargs):
        return self.view.show_viewmarks

    def has_change_permission(self, obj=None):
        if not obj or self.user.is_superuser:
            return True
        else:
            return obj.user == self.user

    def get_context(self, context):
        if not self.show_viewmarks:
            return context

        viewmarks = []

        current_qs = '&'.join(['%s=%s' % (k, v) for k, v in sorted(
            [i for i in list(self.request.GET.items()) if
             bool(i[1] and (i[0] in (COL_LIST_VAR, ORDER_VAR, SEARCH_VAR) or i[0].startswith(FILTER_PREFIX)
                            or i[0].startswith(RELATE_PREFIX)))])])

        model_info = (self.opts.app_label, self.opts.model_name)
        has_selected = False
        menu_title = '视图'
        list_base_url = reverse('%s:%s_%s_changelist' % (self.website.namespace,
                                                         *model_info), current_app=self.website.module_name)

        # local viewmarks
        for bk in self.list_viewmarks:
            title = bk['title']
            params = dict(
                [(FILTER_PREFIX + k, v) for (k, v) in list(bk['query'].items())])
            if 'order' in bk:
                params[ORDER_VAR] = '.'.join(bk['order'])
            if 'cols' in bk:
                params[COL_LIST_VAR] = '.'.join(bk['cols'])
            if 'search' in bk:
                params[SEARCH_VAR] = bk['search']

            def check_item(i):
                return bool(i[1]) or i[1] == False

            bk_qs = '&'.join(['%s=%s' % (k, v) for k, v in sorted(filter(check_item, list(params.items())))])

            url = list_base_url + '?' + bk_qs
            selected = (current_qs == bk_qs)

            viewmarks.append(
                {'title': title, 'selected': selected, 'url': url})
            if selected:
                menu_title = title
                has_selected = True

        content_type = ContentType.objects.get_for_model(self.model)
        bk_model_info = (Viewmark._meta.app_label, Viewmark._meta.model_name)
        viewmarks_queryset = Viewmark.objects.filter(
            content_type=content_type,
            url_name='%s:%s_%s_changelist' % (self.website.namespace, *model_info)
        ).filter(Q(user=self.user) | Q(is_share=True))

        for bk in viewmarks_queryset:
            selected = (current_qs == bk.query)

            if self.has_change_permission(bk):
                change_or_detail = 'change'
            else:
                change_or_detail = 'detail'

            viewmarks.append({'title': bk.title, 'selected': selected, 'url': bk.url, 'edit_url':
                reverse('%s:%s_%s_%s' % (self.website.namespace, bk_model_info[0], bk_model_info[1], change_or_detail),
                        args=(bk.id,))})
            if selected:
                menu_title = bk.title
                has_selected = True

        post_url = reverse('%s:%s_%s_viewmark' % (self.website.namespace, *model_info),
                           current_app=self.website.module_name)

        new_context = {
            'bk_menu_title': menu_title,
            'bk_viewmarks': viewmarks,
            'bk_current_qs': current_qs,
            'bk_has_selected': has_selected,
            'bk_list_base_url': list_base_url,
            'bk_post_url': post_url,
            'has_add_permission_viewmark': self.view.request.user.has_perm('website.add_viewmark'),
            'has_change_permission_viewmark': self.view.request.user.has_perm('website.change_viewmark')
        }
        context.update(new_context)
        return context

    # Media
    def get_media(self, media):
        return media + self.vendor('website.plugin.viewmark.js')

    # Block Views
    def block_nav_menu(self, context, nodes):
        if self.show_viewmarks:
            nodes.insert(0, dutils.render_to_string('website/blocks/model_list.nav_menu.viewmarks.tpl',
                                                    context_instance=context))


# </editor-fold>

# <editor-fold desc="图表插件">
"""
图表插件
=========

功能
----

在数据列表页面, 跟列表数据生成图表. 可以指定多个数据列, 生成多个图表.

截图
----

.. image:: /images/plugins/chart.png

使用
----

在 Model iview 中设定 ``data_charts`` 属性, 该属性为 dict 类型, key 是图表的标示名称, value 是图表的具体设置属性. 使用示例::

    class RecordAdmin(object):
        data_charts = {
            "user_count": {'title': u"User Report", "x-field": "date", "y-field": ("user_count", "view_count"), "order": ('date',)},
            "avg_count": {'title': u"Avg Report", "x-field": "date", "y-field": ('avg_count',), "order": ('date',)}
        }

图表的主要属性为:

    ``title`` : 图表的显示名称

    ``x-field`` : 图表的 X 轴数据列, 一般是日期, 时间等

    ``y-field`` : 图表的 Y 轴数据列, 该项是一个 list, 可以同时设定多个列, 这样多个列的数据会在同一个图表中显示

    ``order`` : 排序信息, 如果不写则使用数据列表的排序

版本
----

暂无

API
---
.. autoclass:: ChartsPlugin
.. autoclass:: ChartsViewTemplate

"""


class ChartsPlugin(ViewPlugin):
    data_charts = {}

    def init_request(self, *args, **kwargs):
        return bool(self.data_charts)

    def get_chart_url(self, name, v):
        return self.view.model_admin_url('chart', name) + self.view.get_query_string()

    # Media
    def get_media(self, media):
        return media + self.vendor('flot.js', 'website.plugin.charts.js')

    # Block Views
    def block_results_top(self, context, nodes):
        context.update({
            'charts': [{"name": name, "title": v['title'], 'url': self.get_chart_url(name, v)} for name, v in
                       list(self.data_charts.items())],
        })
        box_tpl = self.website.style_adminlte and 'website/includes/box_ext.tpl' or 'website/includes/box.tpl'
        context['box_tpl'] = box_tpl
        nodes.append(
            dutils.render_to_string('website/blocks/model_list.results_top.charts.tpl', context_instance=context))


# </editor-fold>

# <editor-fold desc="列表查看编辑插件">
"""
显示数据详情
============

功能
----

该插件可以在列表页中显示相关字段的详细信息, 使用 Ajax 在列表页中显示.

截图
----

.. image:: /images/plugins/details.png

使用
----

使用该插件主要设置 iview 的 ``show_detail_fields``, ``show_all_rel_details`` 两个属性. ``show_detail_fields`` 属性设置哪些字段要显示详细信息,
``show_all_rel_details`` 属性设置时候自动显示所有关联字段的详细信息, 该属性默认为 ``True``. 示例如下::

    class MyModelAdmin(object):

        show_detail_fields = ['group', 'father', ...]

"""


class DetailsPlugin(ViewPlugin):
    show_detail_fields = []
    show_all_rel_details = True

    def makecell(self, item, obj, field_name, row):
        if (self.show_all_rel_details or (field_name in self.show_detail_fields)):

            rel_obj = None
            if isinstance(item.field, models.ForeignKey):
                rel_obj = getattr(obj, field_name)
            elif field_name in self.show_detail_fields:
                rel_obj = obj
            if rel_obj:
                if rel_obj.__class__ in self.website.modelconfigs:
                    try:
                        model_admin = self.website.modelconfigs[rel_obj.__class__]
                        has_view_perm = model_admin(self.view.request).has_view_permission(rel_obj)
                        has_change_perm = model_admin(self.view.request).has_change_permission(rel_obj)
                    except:
                        has_view_perm = self.view.has_model_perm(rel_obj.__class__, 'view')
                        has_change_perm = self.has_model_perm(rel_obj.__class__, 'change')
                else:
                    has_view_perm = self.view.has_model_perm(rel_obj.__class__, 'view')
                    has_change_perm = self.has_model_perm(rel_obj.__class__, 'change')

            if rel_obj and has_view_perm:
                opts = rel_obj._meta
                try:
                    item_res_uri = reverse(
                        '%s:%s_%s_detail' % (self.website.module_name,
                                             opts.app_label, opts.model_name),
                        args=(getattr(rel_obj, opts.pk.attname),))
                    if item_res_uri:
                        if has_change_perm:
                            edit_url = reverse(
                                '%s:%s_%s_change' % (self.website.module_name, opts.app_label, opts.model_name),
                                args=(getattr(rel_obj, opts.pk.attname),))
                        else:
                            edit_url = ''
                        item.btns.append(
                            '<a data-res-uri="%s" data-edit-uri="%s" class="details-handler" rel="tooltip" title="%s"><i class="fa fa-info-circle"></i></a>'
                            % (item_res_uri, edit_url, _('Details of %s') % escape(escape(str(rel_obj)))))
                except NoReverseMatch:
                    pass
        return item

    # Media
    def get_media(self, media):
        if self.show_all_rel_details or self.show_detail_fields:
            media = media + self.vendor('website.plugin.details.js', 'website.form.css')
        return media


"""
数据即时编辑
============

功能
----

该插件可以在列表页中即时编辑某字段的值, 使用 Ajax 技术, 无需提交或刷新页面即可完成数据的修改, 对于需要频繁修改的字段(如: 状态)相当有用.

截图
----

.. image:: /images/plugins/editable.png

使用
----

使用该插件主要设置 iview 的 ``list_editable`` 属性. ``list_editable`` 属性设置哪些字段需要即时修改功能. 示例如下::

    class MyModelAdmin(object):

        list_editable = ['price', 'status', ...]

"""


class EditablePlugin(ViewPlugin):
    list_editable = []
    editable_media = False

    def __init__(self, view):
        super(EditablePlugin, self).__init__(view)
        self.editable_need_fields = {}

    def init_request(self, *args, **kwargs):
        active = bool(self.request.method == 'GET' and self.view.has_change_permission() and self.list_editable)
        if active:
            self.model_form = self.getmodelviewclass(ModelFormViewTemplate, self.model).form_obj
        return active

    def makecell(self, item, obj, field_name, row):
        if self.list_editable and item.field and item.field.editable and (field_name in self.list_editable):
            pk = getattr(obj, obj._meta.pk.attname)
            field_label = label_for_field(field_name, obj,
                                          model_admin=self.view,
                                          return_attr=False
                                          )

            item.wraps.insert(0, '<span class="editable-field">%s</span>')
            item.btns.append((
                                     '<a class="editable-handler" title="%s" data-editable-field="%s" data-editable-loadurl="%s">' +
                                     '<i class="fa fa-edit"></i></a>') %
                             (_("Enter %s") % field_label, field_name,
                              self.view.model_admin_url('patch', pk) + '?fields=' + field_name))

            if field_name not in self.editable_need_fields:
                self.editable_need_fields[field_name] = item.field
        return item

    # Media
    def get_media(self, media):
        if self.editable_need_fields or self.editable_media:
            media = media + self.model_form.media + \
                    self.vendor(
                        'website.plugin.editable.js', 'website.widget.editable.css')
        return media


# </editor-fold>

# <editor-fold desc="导出插件">
"""
数据导出
默认情况下, xadmin 会提供 Excel, CSV, XML, json 四种格式的数据导出.
可以通过设置 list_export 属性来指定使用哪些导出格式 (四种各使用分别用 ``xls``, ``csv``, ``xml``, ``json`` 表示)
将 list_export 设置为 None 来禁用数据导出功能.
"""
try:
    import xlwt

    has_xlwt = True
except:
    has_xlwt = False

try:
    import xlsxwriter

    has_xlsxwriter = True
except:
    has_xlsxwriter = False


class ExportMenuPlugin(ViewPlugin):
    list_export = ('xlsx', 'xls', 'csv', 'xml', 'json')
    export_names = {'xlsx': 'Excel 2007', 'xls': 'Excel', 'csv': 'CSV',
                    'xml': 'XML', 'json': 'JSON'}

    def init_request(self, *args, **kwargs):
        self.list_export = [
            f for f in self.list_export
            if (f != 'xlsx' or has_xlsxwriter) and (f != 'xls' or has_xlwt)]

    def block_top_toolbar(self, context, nodes):
        if self.list_export:
            context.update({
                'show_export_all': self.view.paginator.count > self.view.list_per_page and not ALL_VAR in self.view.request.GET,
                'form_params': self.view.get_form_params({'_do_': 'export'}, ('export_type',)),
                'export_types': [{'type': et, 'name': self.export_names[et]} for et in self.list_export],
            })
            nodes.append(
                render_to_string('website/blocks/model_list.top_toolbar.exports.tpl', context_instance=context))


class ExportPlugin(ViewPlugin):
    export_mimes = {'xlsx': 'application/vnd.ms-excel',
                    'xls': 'application/vnd.ms-excel', 'csv': 'text/csv',
                    'xml': 'application/xhtml+xml', 'json': 'application/json'}

    def init_request(self, *args, **kwargs):
        '''
        当列表页 url 中包含 _do_=export 时识别为导出请求
        '''
        return self.request.GET.get('_do_') == 'export'

    def _format_value(self, o):
        if (o.field is None and getattr(o.attr, 'boolean', False)) or \
                (o.field and isinstance(o.field, (BooleanField, NullBooleanField))):
            value = o.value
        elif str(o.text).startswith("<span class='text-muted'>"):
            value = escape(str(o.text)[25:-7])
        else:
            value = escape(str(o.text))
        return value

    def _get_objects(self, context):
        headers = [c for c in context['result_headers'].cells if c.export]
        rows = context['results']

        return [dict([
            (force_str(headers[i].text), self._format_value(o)) for i, o in
            enumerate([c for c in r.cells if getattr(c, 'export', False)])]) for r in rows]

    def _get_datas(self, context):
        rows = context['results']

        new_rows = [[self._format_value(o) for o in
                     [c for c in r.cells if getattr(c, 'export', False)]] for r in rows]
        new_rows.insert(0, [force_str(c.text) for c in context['result_headers'].cells if c.export])
        return new_rows

    def get_xlsx_export(self, context):
        '''
        导出 xlsx
        '''
        datas = self._get_datas(context)
        output = io.StringIO()
        export_header = (
                self.request.GET.get('export_xlsx_header', 'off') == 'on')

        model_name = self.opts.verbose_name
        book = xlsxwriter.Workbook(output)
        sheet = book.add_worksheet(
            "%s %s" % (_('Sheet'), force_str(model_name)))
        styles = {'datetime': book.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'}),
                  'date': book.add_format({'num_format': 'yyyy-mm-dd'}),
                  'time': book.add_format({'num_format': 'hh:mm:ss'}),
                  'header': book.add_format(
                      {'font': 'name Times New Roman', 'color': 'red', 'bold': 'on', 'num_format': '#,##0.00'}),
                  'default': book.add_format()}

        if not export_header:
            datas = datas[1:]
        for rowx, row in enumerate(datas):
            for colx, value in enumerate(row):
                if export_header and rowx == 0:
                    cell_style = styles['header']
                else:
                    if isinstance(value, datetime.datetime):
                        cell_style = styles['datetime']
                    elif isinstance(value, datetime.date):
                        cell_style = styles['date']
                    elif isinstance(value, datetime.time):
                        cell_style = styles['time']
                    else:
                        cell_style = styles['default']
                sheet.write(rowx, colx, value, cell_style)
        book.close()

        output.seek(0)
        return output.getvalue()

    def get_xls_export(self, context):
        '''
        导出 xls
        '''
        datas = self._get_datas(context)
        output = io.StringIO()
        export_header = (
                self.request.GET.get('export_xls_header', 'off') == 'on')

        model_name = self.opts.verbose_name if self.opts else self.view.verbose_name
        book = xlwt.Workbook(encoding='utf8')
        sheet = book.add_sheet(
            "%s %s" % (_('Sheet'), model_name))
        styles = {'datetime': xlwt.easyxf(num_format_str='yyyy-mm-dd hh:mm:ss'),
                  'date': xlwt.easyxf(num_format_str='yyyy-mm-dd'),
                  'time': xlwt.easyxf(num_format_str='hh:mm:ss'),
                  'header': xlwt.easyxf('font: name Times New Roman, color-index red, bold on',
                                        num_format_str='#,##0.00'),
                  'default': xlwt.Style.default_style}

        if not export_header:
            datas = datas[1:]
        for rowx, row in enumerate(datas):
            for colx, value in enumerate(row):
                if export_header and rowx == 0:
                    cell_style = styles['header']
                else:
                    if isinstance(value, datetime.datetime):
                        cell_style = styles['datetime']
                    elif isinstance(value, datetime.date):
                        cell_style = styles['date']
                    elif isinstance(value, datetime.time):
                        cell_style = styles['time']
                    else:
                        cell_style = styles['default']
                sheet.write(rowx, colx, value, style=cell_style)
        book.save(output)

        output.seek(0)
        return output.getvalue()

    def _format_csv_text(self, t):
        if isinstance(t, bool):
            return '"是"' if t else '"否"'
        t = t.replace('"', '""').replace(',', '\,')
        if isinstance(t, str):
            t = '"%s"' % t
        return t

    def get_csv_export(self, context):
        datas = self._get_datas(context)
        stream = []

        if self.request.GET.get('export_csv_header', 'off') != 'on':
            datas = datas[1:]

        for row in datas:
            stream.append(','.join(map(self._format_csv_text, row)))

        return '\r\n'.join(stream)  # 文件主要面向windows平台

    def _to_xml(self, xml, data):
        if isinstance(data, (list, tuple)):
            for item in data:
                xml.startElement("row", {})
                self._to_xml(xml, item)
                xml.endElement("row")
        elif isinstance(data, dict):
            for key, value in list(data.items()):
                key = key.replace(' ', '_')
                xml.startElement(key, {})
                self._to_xml(xml, value)
                xml.endElement(key)
        else:
            xml.characters(smart_str(data))

    def get_xml_export(self, context):
        results = self._get_objects(context)
        stream = io.StringIO()

        xml = SimplerXMLGenerator(stream, "utf-8")
        xml.startDocument()
        xml.startElement("objects", {})

        self._to_xml(xml, results)

        xml.endElement("objects")
        xml.endDocument()

        return stream.getvalue().split('\n')[1]

    def get_json_export(self, context):
        results = self._get_objects(context)
        return json.dumps({'objects': results}, ensure_ascii=False,
                          indent=(self.request.GET.get('export_json_format', 'off') == 'on') and 4 or None)

    def get_response(self, response, context, *args, **kwargs):
        file_type = self.request.GET.get('export_type', 'csv')
        response = HttpResponse(
            content_type="%s; charset=UTF-8" % self.export_mimes[file_type])

        file_name = self.opts.verbose_name.replace(' ', '_') if self.opts else self.view.verbose_name
        response['Content-Disposition'] = ('attachment; filename=%s.%s' % (
            file_name, file_type)).encode('utf-8')

        response.write(getattr(self, 'get_%s_export' % file_type)(context))
        return response

    # View Methods
    def get_result_list(self, __):
        '''
        控制导出的grid数据
        '''
        if self.request.GET.get('all', 'off') == 'on':
            self.view.list_per_page = EXPORT_MAX  # sys.maxint
        return __()

    def makeheader(self, item, field_name, row):
        '''
        控制是否导出
        '''
        item.export = not item.attr or field_name == '__str__' or getattr(item.attr, 'allow_export', True)
        if field_name == 'action_checkbox':
            item.export = False
        return item

    def makecell(self, item, obj, field_name, row):
        item.export = item.field or field_name == '__str__' or getattr(item.attr, 'allow_export', True)
        if field_name == 'action_checkbox':
            item.export = False
        return item


# </editor-fold>

# <editor-fold desc="数据过滤插件">
"""
数据过滤器
list_filter
search_fields
free_query_filter
"""


class IncorrectLookupParameters(Exception):
    pass


class FilterPlugin(ViewPlugin):
    list_filter = ()
    search_fields = []
    free_query_filter = True
    filter_default_list = []
    filter_list_position = None

    def __init__(self, view):
        super().__init__(view)

        self.filter_specs = []
        self.filter_default = []
        self.has_filters = False

    def init_request(self, *args, **kwargs):
        return super(FilterPlugin, self).init_request(*args, **kwargs)

    def lookup_allowed(self, lookup, value):
        print('lookup_allowed')
        model = self.model
        # Check FKey lookups that are allowed, so that popups produced by
        # ForeignKeyRawIdWidget, on the basis of ForeignKey.limit_choices_to,
        # are allowed to work.
        for l in model._meta.related_fkey_lookups:
            for k, v in list(website.views.widgets.url_params_from_lookup_dict(l).items()):
                if k == lookup and v == value:
                    return True

        parts = lookup.split(LOOKUP_SEP)

        # Last term in lookup is a query term (__exact, __startswith etc)
        # This term can be ignored.
        if len(parts) > 1 and parts[-1] in QUERY_TERMS:
            parts.pop()

        # Special case -- foo__id__exact and foo__id queries are implied
        # if foo has been specificially included in the lookup list; so
        # drop __id if it is the last part. However, first we need to find
        # the pk attribute name.
        rel_name = None
        for part in parts[:-1]:
            try:
                field, _, _, _ = model._meta.get_field_by_name(part)
            except FieldDoesNotExist:
                # Lookups on non-existants fields are ok, since they're ignored
                # later.
                return True
            if hasattr(field, 'remote_field'):
                model = field.remote_field.model
                rel_name = field.remote_field.name
            elif isinstance(field, RelatedObject):
                model = field.model
                rel_name = model._meta.pk.name
            else:
                rel_name = None
        if rel_name and len(parts) > 1 and parts[-1] == rel_name:
            parts.pop()

        if len(parts) == 1:
            return True
        clean_lookup = LOOKUP_SEP.join(parts)
        return clean_lookup in self.list_filter

    def get_list_queryset(self, queryset):
        lookup_params = dict([(k[len('_p_'):], v) for k, v in self.view.params.items()
                              if k.startswith('_p_') and v != ''])
        # print('queryset:', lookup_params)

        for p_key, p_val in lookup_params.items():
            if p_val == "False":
                lookup_params[p_key] = False
        use_distinct = False

        # for clean filters
        self.view.has_query_param = bool(lookup_params)
        self.view.clean_query_url = self.view.get_query_string(remove=
                                                               [k for k in self.request.GET.keys() if
                                                                k.startswith(FILTER_PREFIX)])

        # Normalize the types of keys
        if not self.free_query_filter:
            for key, value in list(lookup_params.items()):
                if not self.lookup_allowed(key, value):
                    raise SuspiciousOperation(
                        "Filtering by %s not allowed" % key)

        if self.view.list_filter:
            for list_filter in self.view.list_filter:
                if callable(list_filter):
                    spec = list_filter(self.request, lookup_params, self.model, self.view)
                else:
                    field_path = None
                    field_parts = []
                    if isinstance(list_filter, (tuple, list)):
                        field, field_list_filter_class = list_filter
                        # print('filter class:',field, field_list_filter_class)
                    else:
                        field, field_list_filter_class = list_filter, filter_manager.create
                    if not isinstance(field, models.Field):
                        field_path = field
                        field_parts = get_fields_from_path(self.model, field_path)
                        field = field_parts[-1]
                    spec = field_list_filter_class(field, self.request, lookup_params,
                                                   self.model, self.view, field_path=field_path)
                    if len(field_parts) > 1:
                        spec.title = "%s%s" % (field_parts[-2].related_model._meta.verbose_name, spec.title)
                    use_distinct = (use_distinct or lookup_needs_distinct(self.opts, field_path))
                # print('has output:',spec.has_output())
                if spec and spec.has_output():
                    try:
                        new_qs = spec.do_filte(queryset)
                    except ValidationError as e:
                        new_qs = None
                        self.view.message_user(_("<b>Filtering error:</b> %s") % e.messages[0], 'error')
                    if new_qs is not None:
                        queryset = new_qs

                    self.filter_specs.append(spec)
                    if list_filter in self.filter_default_list:
                        postfix = 'top' if self.filter_list_position == 'top' else 'box'
                        spec.template = spec.template.replace('.tpl', '_%s.tpl' % postfix)
                        self.filter_default.append(spec)

        self.has_filters = bool(self.filter_specs)
        self.view.filter_specs = self.filter_specs
        self.view.filter_default = self.filter_default
        self.view.used_filter_num = len([f for f in self.filter_specs if f.is_used and f not in self.filter_default])

        try:
            for key, value in list(lookup_params.items()):
                use_distinct = (use_distinct or False)  # lookup_needs_distinct(self.opts, key))
        except FieldDoesNotExist as e:
            raise IncorrectLookupParameters(e)

        try:
            m_lookup_params = copy.deepcopy(lookup_params)
            for k, v in list(lookup_params.items()):
                if k.endswith('__in'):
                    m_v = v.split(',')
                    m_lookup_params[k] = m_v
            queryset = queryset.filter(**m_lookup_params)
        except (SuspiciousOperation, ImproperlyConfigured):
            raise
        except Exception as e:
            raise IncorrectLookupParameters(e)

        ######## search part
        query = self.request.GET.get(SEARCH_VAR, '')

        def construct_search(field_name):
            if field_name.startswith('^'):
                return "%s__istartswith" % field_name[1:]
            elif field_name.startswith('='):
                return "%s__iexact" % field_name[1:]
            elif field_name.startswith('@'):
                return "%s__search" % field_name[1:]
            else:
                return "%s__icontains" % field_name

        if self.search_fields and query:
            if not self.view.search_sphinx_ins:
                orm_lookups = [construct_search(str(search_field))
                               for search_field in self.search_fields]
                for bit in query.split():
                    or_queries = [models.Q(**{orm_lookup: bit})
                                  for orm_lookup in orm_lookups]
                    queryset = queryset.filter(reduce(operator.or_, or_queries))
                if not use_distinct:
                    for search_spec in orm_lookups:
                        if lookup_needs_distinct(self.opts, search_spec):
                            use_distinct = True
                            break
            self.view.search_query = query

        if use_distinct:
            return queryset.distinct()
        else:
            return queryset

    def get_media(self, media):
        if bool(list(filter(lambda s: isinstance(s, DateFieldListFilter) or isinstance(s, DateBaseFilter),
                            self.filter_specs))):
            media = media + self.vendor('datepicker.css', 'datepicker.js',
                                        'website.widget.datetime.js')
        if bool(list(filter(lambda s: isinstance(s, RelatedFieldSearchFilter), self.filter_specs))):
            media = media + self.vendor(
                'select.js', 'select.css', 'website.widget.select.js')
        return media + self.vendor('website.plugin.filters.js')

    def block_nav_menu(self, context, nodes):
        if self.has_filters and len(self.filter_specs) > len(self.filter_default):
            nodes.append(render_to_string('website/blocks/filters_menu.tpl', context_instance=context))

    def block_grid_left(self, context, nodes):
        if self.has_filters and self.filter_list_position == 'left':
            nodes.append(render_to_string('website/blocks/filters_left.tpl', context_instance=context))

    def block_grid_top(self, context, nodes):
        if self.has_filters and self.filter_list_position == 'top':
            nodes.append(render_to_string('website/blocks/filters_top.tpl', context_instance=context))

    def block_nav_form(self, context, nodes):
        if self.search_fields:
            context.update({'search_var': SEARCH_VAR,
                            'remove_search_url': self.view.get_query_string(remove=[SEARCH_VAR]),
                            'search_form_params': self.view.get_form_params(remove=[SEARCH_VAR, 'p'])})
            nodes.append(
                render_to_string('website/blocks/search_form.tpl', context_instance=context))


class QuickFilterPlugin(ViewPlugin):
    list_quick_filter = ()  # these must be a subset of list_filter to work
    quickfilter = {}

    search_fields = ()
    free_query_filter = True

    def init_request(self, *args, **kwargs):
        style_menu_accordian = hasattr(self.view, 'style_menu') and self.view.style_menu == 'accordion'
        return bool(self.list_quick_filter) and not style_menu_accordian

    # Media
    def get_media(self, media):
        return media + self.vendor('website.plugin.quickfilter.js', 'website.plugin.quickfilter.css')

    def lookup_allowed(self, lookup, value):
        model = self.model
        # Check FKey lookups that are allowed, so that popups produced by
        # ForeignKeyRawIdWidget, on the basis of ForeignKey.limit_choices_to,
        # are allowed to work.
        for l in model._meta.related_fkey_lookups:
            for k, v in list(website.views.widgets.url_params_from_lookup_dict(l).items()):
                if k == lookup and v == value:
                    return True

        parts = lookup.split(LOOKUP_SEP)

        # Last term in lookup is a query term (__exact, __startswith etc)
        # This term can be ignored.
        if len(parts) > 1 and parts[-1] in QUERY_TERMS:
            parts.pop()

        # Special case -- foo__id__exact and foo__id queries are implied
        # if foo has been specificially included in the lookup list; so
        # drop __id if it is the last part. However, first we need to find
        # the pk attribute name.
        rel_name = None
        for part in parts[:-1]:
            try:
                field, _, _, _ = model._meta.get_field_by_name(part)
            except FieldDoesNotExist:
                # Lookups on non-existants fields are ok, since they're ignored
                # later.
                return True
            if hasattr(field, 'remote_field'):
                model = field.remote_field.model
                rel_name = field.remote_field.name
            elif isinstance(field, RelatedObject):
                model = field.model
                rel_name = model._meta.pk.name
            else:
                rel_name = None
        if rel_name and len(parts) > 1 and parts[-1] == rel_name:
            parts.pop()

        if len(parts) == 1:
            return True
        clean_lookup = LOOKUP_SEP.join(parts)
        return clean_lookup in self.list_quick_filter

    def get_list_queryset(self, queryset):
        lookup_params = dict([(smart_str(k)[len(FILTER_PREFIX):], v) for k, v in list(self.view.params.items()) if
                              smart_str(k).startswith(FILTER_PREFIX) and v != ''])
        for p_key, p_val in list(lookup_params.items()):
            if p_val == "False":
                lookup_params[p_key] = False
        use_distinct = False

        if not hasattr(self.view, 'quickfilter'):
            self.view.quickfilter = {}

        # for clean filters
        self.view.quickfilter['has_query_param'] = bool(lookup_params)
        self.view.quickfilter['clean_query_url'] = self.view.get_query_string(
            remove=[k for k in list(self.request.GET.keys()) if k.startswith(FILTER_PREFIX)])

        # Normalize the types of keys
        if not self.free_query_filter:
            for key, value in list(lookup_params.items()):
                if not self.lookup_allowed(key, value):
                    raise SuspiciousOperation("Filtering by %s not allowed" % key)

        self.filter_specs = []
        if self.list_quick_filter:
            for list_quick_filter in self.list_quick_filter:
                field_path = None
                field_order_by = None
                field_limit = None
                field_parts = []
                sort_key = None
                cache_config = None

                if type(list_quick_filter) == dict and 'field' in list_quick_filter:
                    field = list_quick_filter['field']
                    if 'order_by' in list_quick_filter:
                        field_order_by = list_quick_filter['order_by']
                    if 'limit' in list_quick_filter:
                        field_limit = list_quick_filter['limit']
                    if 'sort' in list_quick_filter and callable(list_quick_filter['sort']):
                        sort_key = list_quick_filter['sort']
                    if 'cache' in list_quick_filter and type(list_quick_filter) == dict:
                        cache_config = list_quick_filter['cache']

                else:
                    field = list_quick_filter  # This plugin only uses MultiselectFieldListFilter

                if not isinstance(field, models.Field):
                    field_path = field
                    field_parts = get_fields_from_path(self.model, field_path)
                    field = field_parts[-1]
                spec = QuickFilterMultiSelectFieldListFilter(field, self.request, lookup_params, self.model,
                                                             self.view, field_path=field_path,
                                                             field_order_by=field_order_by, field_limit=field_limit,
                                                             sort_key=sort_key, cache_config=cache_config)

                if len(field_parts) > 1:
                    spec.title = "%s %s" % (field_parts[-2].name, spec.title)

                    # Check if we need to use distinct()
                use_distinct = True  # (use_distinct orlookup_needs_distinct(self.opts, field_path))
                if spec and spec.has_output():
                    try:
                        new_qs = spec.do_filte(queryset)
                    except ValidationError as e:
                        new_qs = None
                        self.view.message_user("<b>过滤器错误:</b> %s" % e.messages[0], 'error')
                    if new_qs is not None:
                        queryset = new_qs

                    self.filter_specs.append(spec)

        self.has_filters = bool(self.filter_specs)
        self.view.quickfilter['filter_specs'] = self.filter_specs
        self.view.quickfilter['used_filter_num'] = len([f for f in self.filter_specs if f.is_used])

        if use_distinct:
            return queryset.distinct()
        else:
            return queryset

    def block_left_navbar(self, context, nodes):
        nodes.append(
            render_to_string('website/blocks/filters_quick.tpl', context_instance=context))


# </editor-fold>

# <editor-fold desc="图片走廊插件">
def get_gallery_modal():
    return """
        <!-- modal-gallery is the modal dialog used for the image gallery -->
        <div id="modal-gallery" class="modal modal-gallery fade" tabindex="-1">
          <div class="modal-dialog">
            <div class="modal-content">
              <div class="modal-header">
                <button type="button" class="close" data-dismiss="modal" aria-hidden="true">&times;</button>
                <h4 class="modal-title"></h4>
              </div>
              <div class="modal-body"><div class="modal-image"><h1 class="loader"><i class="fa-spinner fa-spin fa fa-large loader"></i></h1></div></div>
              <div class="modal-footer">
                  <a class="btn btn-info modal-prev"><i class="fa fa-arrow-left"></i> <span>%s</span></a>
                  <a class="btn btn-primary modal-next"><span>%s</span> <i class="fa fa-arrow-right"></i></a>
                  <a class="btn btn-success modal-play modal-slideshow" data-slideshow="5000"><i class="fa fa-play"></i> <span>%s</span></a>
                  <a class="btn btn-default modal-download" target="_blank"><i class="fa fa-download"></i> <span>%s</span></a>
              </div>
            </div><!-- /.modal-content -->
          </div><!-- /.modal-dialog -->
        </div>
    """ % (_('Previous'), _('Next'), _('Slideshow'), _('Download'))


class ModelDetailPlugin(ViewPlugin):
    def __init__(self, view):
        super(ModelDetailPlugin, self).__init__(view)
        self.include_image = hasattr(view, 'include_image') and view.include_image or False

    def get_field_attrs(self, attrs, db_field, **kwargs):
        if isinstance(db_field, models.ImageField):
            attrs['widget'] = ImageWidget
            attrs['form_class'] = AdminImageField
            self.include_image = True
        return attrs

    def get_field_result(self, result, field_name):
        if isinstance(result.field, models.ImageField):
            if result.value:
                img = getattr(result.obj, field_name)
                db_value = str(img)
                if db_value.startswith('/'):
                    file_path = urllib.parse.urljoin(settings.REMOTE_MEDIA_URL, db_value)
                else:
                    file_path = img.url
                result.text = mark_safe(
                    '<a href="%s" target="_blank" title="%s" data-gallery="gallery"><img src="%s" class="field_img"/></a>' % (
                        file_path, result.label, file_path))
                self.include_image = True
        return result

    # Media
    def get_media(self, media):
        if self.include_image:
            media = media + self.vendor('image-gallery.js',
                                        'image-gallery.css') + self.vendor('website.plugin.imgupload.js')
        return media

    def block_before_fieldsets(self, context, node):
        if self.include_image:
            return '<div id="gallery" data-toggle="modal-gallery" data-target="#modal-gallery">'

    def block_after_fieldsets(self, context, node):
        if self.include_image:
            return "</div>"

    def block_extrabody(self, context, node):
        if self.include_image:
            return get_gallery_modal()


class ModelListPlugin(ViewPlugin):
    list_gallery = False

    def init_request(self, *args, **kwargs):
        return bool(self.list_gallery)

    def makecell(self, item, obj, field_name, row):
        opts = obj._meta
        try:
            f = opts.get_field(field_name)
        except models.FieldDoesNotExist:
            f = None
        if f:
            if isinstance(f, models.ImageField):
                img = getattr(obj, field_name)
                if img:
                    db_value = str(img)
                    if db_value.startswith('/'):
                        file_path = urllib.parse.urljoin(settings.REMOTE_MEDIA_URL, db_value)
                    else:
                        file_path = img.url
                    if type(self.list_gallery) == str:
                        file_path = '%s%s' % (file_path, self.list_gallery)
                    item.text = mark_safe(
                        '<a href="%s" target="_blank" data-gallery="gallery"><img src="%s" class="field_img"/></a>' % (
                            file_path, file_path))
        return item

    # Media
    def get_media(self, media):
        return media + self.vendor('image-gallery.js', 'image-gallery.css')

    def block_results_top(self, context, node):
        return '<div id="gallery" data-toggle="modal-gallery" data-target="#modal-gallery">'

    def block_results_bottom(self, context, node):
        return "</div>"

    def block_extrabody(self, context, node):
        return get_gallery_modal()


# </editor-fold>

# <editor-fold desc="设置语言插件">
class SetLangNavPlugin(ViewPlugin):

    def block_top_navmenu(self, context, nodes):
        _context = RequestContext(self.request)
        _context.update({
            'redirect_to': self.request.get_full_path(),
        })
        nodes.append(
            dutils.render_to_string('website/blocks/comm.top.setlang.tpl', context_instance=_context))


# </editor-fold>

# <editor-fold desc="内联插件">
def replace_field_to_value(layout, av):
    '''
    用于将字段显示为只读值
    '''
    if layout:
        for i, lo in enumerate(layout.fields):
            if isinstance(lo, Field) or issubclass(lo.__class__, Field):
                layout.fields[i] = InlineShowField(av, *lo.fields, **lo.attrs)
            elif isinstance(lo, str):
                layout.fields[i] = InlineShowField(av, lo)
            elif hasattr(lo, 'get_field_names'):
                replace_field_to_value(lo, av)


def get_first_field(layout, clz):
    for layout_object in layout.fields:
        if issubclass(layout_object.__class__, clz):
            return layout_object
        elif hasattr(layout_object, 'get_field_names'):
            gf = get_first_field(layout_object, clz)
            if gf:
                return gf


def replace_inline_objects(layout, fs):
    if not fs:
        return
    for i, layout_object in enumerate(layout.fields):
        if isinstance(layout_object, Inline) and layout_object.model in fs:
            layout.fields[i] = fs.pop(layout_object.model)
        elif hasattr(layout_object, 'get_field_names'):
            replace_inline_objects(layout_object, fs)


class InlineFormsetPlugin(ViewPlugin):
    inlines = []

    @property
    def inline_instances(self):
        if not hasattr(self, '_inline_instances'):
            inline_instances = []
            for inline_class in self.inlines:
                inline = self.view.getviewclass(
                    (getattr(inline_class, 'generic_inline',
                             False) and GenericInlineModelView or InlineFormViewTemplate),
                    inline_class).init(self.view)
                if not (inline.has_add_permission() or
                        inline.has_change_permission() or
                        inline.has_delete_permission() or
                        inline.has_view_permission()):
                    continue
                if not inline.has_add_permission():
                    inline.max_num = 0
                inline_instances.append(inline)
            self._inline_instances = inline_instances
        return self._inline_instances

    def instance_forms(self, ret):
        self.formsets = []
        for inline in self.inline_instances:
            if inline.has_change_permission():
                self.formsets.append(inline.instance_form())
            else:
                self.formsets.append(self._get_detail_formset_instance(inline))
        self.view.formsets = self.formsets

    def valid_forms(self, result):
        return all_valid(self.formsets) and result

    def save_related(self):
        for formset in self.formsets:
            formset.instance = self.view.new_obj
            formset.save()

    def get_context(self, context):
        context['inline_formsets'] = self.formsets
        return context

    def get_error_list(self, errors):
        for fs in self.formsets:
            errors.extend(fs.non_form_errors())
            for errors_in_inline_form in fs.errors:
                errors.extend(list(errors_in_inline_form.values()))
        return errors

    def get_form_layout(self, layout):
        allow_blank = isinstance(self.view, DetailView)
        # fixed #176 bug, change dict to list
        fs = [(f.model, InlineFormset(f, allow_blank)) for f in self.formsets]
        replace_inline_objects(layout, fs)

        if fs:
            container = get_first_field(layout, Column)
            if not container:
                container = get_first_field(layout, Container)
            if not container:
                container = layout

            # fixed #176 bug, change dict to list
            for key, value in fs:
                container.append(value)

        return layout

    def get_media(self, media):
        for fs in self.formsets:
            media = media + fs.media
        if self.formsets:
            media = media + self.vendor(
                'website.plugin.formset.js', 'website.plugin.formset.css')
        return media

    def _get_detail_formset_instance(self, inline):
        formset = inline.instance_form(extra=0, max_num=0, can_delete=0)
        formset.detail_page = True
        if True:
            replace_field_to_value(formset.helper.layout, inline)
            model = inline.model
            opts = model._meta
            fake_admin_class = type(str('%s%sFakeAdmin' % (opts.app_label, opts.model_name)), (object,),
                                    {'model': model})
            for form in formset.forms:
                instance = form.instance
                if instance.pk:
                    form.detail = self.getviewclass(
                        DetailViewMixin, fake_admin_class, instance)
        return formset


class DetailInlineFormsetPlugin(InlineFormsetPlugin):

    def get_model_form(self, form, **kwargs):
        self.formsets = [self._get_detail_formset_instance(
            inline) for inline in self.inline_instances]
        return form


# </editor-fold>

# <editor-fold desc="展示样式插件">
LAYOUT_VAR = '_layout'
DEFAULT_LAYOUTS = {
    'table': {
        'key': 'table',
        'icon': 'fa fa-table',
        'name': '表格',
        'template': 'views/grid.tpl',
    },
    'thumbnails': {
        'key': 'thumbnails',
        'icon': 'fa fa-th-large',
        'name': '看板',
        'template': 'grids/thumbnails.tpl',
    },
}


class GridLayoutPlugin(ViewPlugin):
    grid_layouts = []

    _active_layouts = []
    _current_layout = None
    _current_icon = 'table'

    def get_layout(self, l):
        item = (type(l) is dict) and l or DEFAULT_LAYOUTS[l]
        return dict({'url': self.view.get_query_string({LAYOUT_VAR: item['key']}), 'selected': False}, **item)

    def init_request(self, *args, **kwargs):
        active = bool(self.request.method == 'GET' and self.grid_layouts)
        if active:
            layouts = (type(self.grid_layouts) in (list, tuple)) and self.grid_layouts or (self.grid_layouts,)
            self._active_layouts = [self.get_layout(l) for l in layouts]
            self._current_layout = self.request.GET.get(LAYOUT_VAR, self._active_layouts[0]['key'])
            for layout in self._active_layouts:
                if self._current_layout == layout['key']:
                    self._current_icon = layout['icon']
                    layout['selected'] = True
                    self.view.list_template = self.view.get_template_list(layout['template'])
        return active

    def makecell(self, item, obj, field_name, row):
        if self._current_layout == 'thumbnails':
            if getattr(item.attr, 'is_column', True):
                item.field_label = label_for_field(
                    field_name, self.model,
                    model_admin=self.view,
                    return_attr=False
                )
            if getattr(item.attr, 'thumbnail_img', False):
                setattr(item, 'thumbnail_hidden', True)
                row['thumbnail_img'] = item
            elif item.is_display_link:
                setattr(item, 'thumbnail_hidden', True)
                row['thumbnail_label'] = item

        return item

    # Block Views
    def block_top_toolbar(self, context, nodes):
        if len(self._active_layouts) > 1:
            context.update({
                'layouts': self._active_layouts,
                'current_icon': self._current_icon,
            })
            nodes.append(
                dutils.render_to_string('website/blocks/model_list.top_toolbar.layouts.tpl', context_instance=context))


# </editor-fold>

# <editor-fold desc="手机设备插件">
class MobilePlugin(ViewPlugin):

    def _test_mobile(self):
        try:
            return self.request.META['HTTP_USER_AGENT'].find('Android') >= 0 or \
                   self.request.META['HTTP_USER_AGENT'].find('iPhone') >= 0
        except Exception:
            return False

    def init_request(self, *args, **kwargs):
        return self._test_mobile()

    def get_context(self, context):
        # context['base_template'] = 'website/base_mobile.tpl'
        context['is_mob'] = True
        return context

    # Media
    # def get_media(self, media):
    #     return media + self.vendor('website.mobile.css', )

    def block_extrahead(self, context, nodes):
        nodes.append('<script>window.__admin_ismobile__ = true;</script>')


# </editor-fold>

# <editor-fold desc="门户插件">
class PortalPlugin(ViewPlugin):

    # Media
    def get_media(self, media):
        return media + self.vendor('website.plugin.portal.js')


def get_layout_objects(layout, clz, objects):
    for i, layout_object in enumerate(layout.fields):
        if layout_object.__class__ is clz or issubclass(layout_object.__class__, clz):
            objects.append(layout_object)
        elif hasattr(layout_object, 'get_field_names'):
            get_layout_objects(layout_object, clz, objects)


class ModelFormPlugin(PortalPlugin):

    def _portal_key(self):
        return '%s_%s_editform_portal' % (self.opts.app_label, self.opts.model_name)

    def get_form_helper(self, helper):
        cs = []
        layout = helper.layout
        get_layout_objects(layout, Column, cs)
        for i, c in enumerate(cs):
            if not getattr(c, 'css_id', None):
                c.css_id = 'column-%d' % i

        # make fieldset index
        fs = []
        get_layout_objects(layout, Fieldset, fs)
        fs_map = {}
        for i, f in enumerate(fs):
            if not getattr(f, 'css_id', None):
                f.css_id = 'box-%d' % i
            fs_map[f.css_id] = f

        try:
            layout_pos = UserSetting.objects.get(
                user=self.user, key=self._portal_key()).value
            layout_cs = layout_pos.split('|')
            for i, c in enumerate(cs):
                c.fields = [fs_map.pop(j) for j in layout_cs[i].split(
                    ',') if j in fs_map] if len(layout_cs) > i else []
            if fs_map and cs:
                cs[0].fields.extend(list(fs_map.values()))
        except Exception:
            pass

        return helper

    def block_form_top(self, context, node):
        # put portal key and submit url to page
        return "<input type='hidden' id='_portal_key' value='%s' />" % self._portal_key()


class PortalModelDetailPlugin(ModelFormPlugin):

    def _portal_key(self):
        return '%s_%s_detail_portal' % (self.opts.app_label, self.opts.model_name)

    def block_after_fieldsets(self, context, node):
        # put portal key and submit url to page
        return "<input type='hidden' id='_portal_key' value='%s' />" % self._portal_key()


# </editor-fold>

# <editor-fold desc="快速插件">
class QuickFormPlugin(ViewPlugin):

    def init_request(self, *args, **kwargs):
        if self.request.method == 'GET' and self.request.is_ajax() or self.request.GET.get('_ajax'):
            self.view.add_form_template = 'website/views/quick_form.tpl'
            self.view.change_form_template = 'website/views/quick_form.tpl'
            self.view.template = 'website/views/quick_form.tpl'
            return True
        return False

    def get_model_form(self, __, **kwargs):
        if '_field' in self.request.GET:
            defaults = {
                "form": self.view.form,
                "fields": self.request.GET['_field'].split(','),
                "formfield_callback": self.view.formfield_for_dbfield,
            }
            return modelform_factory(self.model, **defaults)
        return __()

    def get_form_layout(self, __):
        if '_field' in self.request.GET:
            return Layout(*self.request.GET['_field'].split(','))
        return __()

    def get_context(self, context):
        context['form_url'] = self.request.path
        return context


class QuickAddBtnPlugin(ViewPlugin):

    def formfield_for_dbfield(self, formfield, db_field, **kwargs):
        if formfield and self.model in self.website.modelconfigs and isinstance(db_field, (
                models.ForeignKey, models.ManyToManyField)):
            rel_model = get_model_from_relation(db_field)
            if rel_model in self.website.modelconfigs and self.has_model_perm(rel_model, 'add'):
                add_url = self.get_model_url(rel_model, 'add')
                formfield.widget = RelatedFieldWidgetWrapper(
                    formfield.widget, db_field.remote_field, add_url, self.get_model_url(self.model, 'add'))
        return formfield


# </editor-fold>

# <editor-fold desc="定时刷新插件">
"""
列表定时刷新
============

功能
----

该插件在数据列表页面提供了定时刷新功能, 对于需要实时刷新列表页面查看即时数据的情况非常有用.

截图
----

.. image:: /images/plugins/refresh.png

使用
----

使用数据刷新插件非常简单, 设置 iview 的 ``refresh_times`` 属性即可. ``refresh_times`` 属性是存有刷新时间的数组. xadmin 默认不开启该插件.
示例如下::

    class MyModelAdmin(object):

        # 这会显示一个下拉列表, 用户可以选择3秒或5秒刷新一次页面.
        refresh_times = (3, 5)

"""

REFRESH_VAR = '_refresh'


class RefreshPlugin(ViewPlugin):
    refresh_times = []

    # Media
    def get_media(self, media):
        if self.refresh_times and self.request.GET.get(REFRESH_VAR):
            media = media + self.vendor('website.plugin.refresh.js')
        return media

    # Block Views
    def block_top_toolbar(self, context, nodes):
        if self.refresh_times:
            current_refresh = self.request.GET.get(REFRESH_VAR)
            context.update({
                'has_refresh': bool(current_refresh),
                'clean_refresh_url': self.view.get_query_string(remove=(REFRESH_VAR,)),
                'current_refresh': current_refresh,
                'refresh_times': [{
                    'time': r,
                    'url': self.view.get_query_string({REFRESH_VAR: r}),
                    'selected': str(r) == current_refresh,
                } for r in self.refresh_times],
            })
            nodes.append(
                dutils.render_to_string('website/blocks/model_list.top_toolbar.refresh.tpl', context_instance=context))


# </editor-fold>

# <editor-fold desc="关联字段插件">
'''
模型关联相关
'''


class RelateMenuPlugin(ViewPlugin):
    related_list = []
    use_related_menu = True
    use_op_menu = True
    op_menu_btn = True
    use_menu_icon = True
    use_menu_name = False

    @staticmethod
    def get_r_list(model):
        opts = model._meta
        return opts.get_all_related_objects() + opts.get_all_related_many_to_many_objects()

    def get_related_list(self):
        '''
        获取关联的对象
        '''
        if hasattr(self, '_related_acts'):
            return self._related_acts

        _related_acts = []

        _r_list = RelateMenuPlugin.get_r_list(self.model)
        for r in _r_list:
            if self.related_list and (r.get_accessor_name() not in self.related_list):
                continue

            if hasattr(r, 'opts'):
                _model = r.model
            else:
                _model = r.related_model
            if _model not in list(self.website.modelconfigs.keys()):
                continue

            has_view_perm = self.has_model_perm(_model, 'view')
            has_add_perm = self.has_model_perm(_model, 'add')
            if not (has_view_perm or has_add_perm):
                continue

            _related_acts.append((r, has_view_perm, has_add_perm))

        self._related_acts = _related_acts
        if len(_related_acts) > 0:
            self.first_rel_url = self._list_url(_related_acts[0][0])
        return self._related_acts

    def _list_url(self, r):
        info = RelateMenuPlugin.get_r_model_info(r)
        list_url = reverse('%s:%s_%s_changelist' % (self.website.module_name, info['label'], info['model_name']))
        return "%s?%s=" % (list_url, RELATE_PREFIX + info['lookup_name'])

    @staticmethod
    def get_r_model_info(r):
        if hasattr(r, 'opts'):
            opts = r.opts
        else:
            opts = r.related_model._meta
        label = opts.app_label
        model_name = opts.model_name
        f = r.field
        rel_name = f.remote_field.get_related_field().name
        lookup_name = '%s__%s__exact' % (f.name, rel_name)
        verbose_name = force_str(opts.verbose_name)
        return {
            'label': label,
            'model_name': model_name,
            'lookup_name': lookup_name,
            'verbose_name': verbose_name
        }

    def related_link(self, instance):
        '''
        外键关联菜单列
        '''
        links = []
        for r, view_perm, add_perm in self.get_related_list():
            info = RelateMenuPlugin.get_r_model_info(r)
            label = info['label']
            model_name = info['model_name']
            lookup_name = info['lookup_name']
            verbose_name = info['verbose_name']

            _tojoin = ['<li class="with_menu_btn">']

            if view_perm:
                list_url = reverse('%s:%s_%s_changelist' % (self.website.module_name, label, model_name))
                str1 = '<a href="%s?%s=%s" title="查看%s"><i class="icon fa fa-usb"></i> %s</a>' % (
                    list_url,
                    RELATE_PREFIX + lookup_name, str(instance.pk),
                    verbose_name,
                    verbose_name
                )
            else:
                str1 = '<a><span class="text-muted"><i class="icon fa fa-blank"></i> %s</span></a>' % verbose_name
            _tojoin.append(str1)

            if add_perm:
                add_url = reverse('%s:%s_%s_add' % (self.website.module_name, label, model_name))
                str2 = '<a class="add_link dropdown-menu-btn" href="%s?%s=%s" title="添加%s"><i class="icon fa fa-plus pull-right"></i></a>' % (
                    add_url,
                    RELATE_PREFIX + lookup_name,
                    str(instance.pk),
                    verbose_name
                )
            else:
                str2 = ''
            _tojoin.append(str2)

            link = ''.join(_tojoin)
            links.append(link)
        ul_html = '<ul class="dropdown-menu" role="menu">%s</ul>' % ''.join(links)
        return '<div class="dropdown related_menu pull-right"><a title="%s" class="relate_menu dropdown-toggle" data-toggle="dropdown"><i class="icon fa fa-ellipsis-v"></i></a>%s</div>' % (
            _('Related Objects'), ul_html)

    related_link.verbose_name = '&nbsp;'
    related_link.allow_tags = True
    related_link.allow_export = False
    related_link.is_column = False

    def op_link(self, instance):
        _model = self.view.model
        links = []
        # if self.has_view_perm:
        #     links.append('''<a %s="%s" data-edit-uri="%s" rel="tooltip" title="%s" %s >%s 查看</a>''' % (
        #         self.op_menu_btn and 'data-res-uri' or 'href', self.view.model_admin_url('detail', instance.pk),
        #         self.view.model_admin_url('change', instance.pk), escape(escape(str(instance))),
        #         self.op_menu_btn and 'class="btn btn-info btn-xs details-handler"' or '',
        #         self.op_menu_btn and '<i class="fa fa-search-plus"></i>' or ''))
        if not self.view.pop and self.has_change_perm:
            links.append('''<a href="%s" %s >%s %s</a>''' % (
                self.view.model_admin_url('change', instance.pk),
                self.op_menu_btn and 'class="btn  btn-xs"' or '',
                self.use_menu_icon and '<i class="fa fa-edit"></i>' or '',
                self.use_menu_name and '修改' or ''))
        if not self.view.pop and self.has_delete_perm:
            links.append('''<a href="%s" %s >%s %s</a>''' % (
                self.view.model_admin_url('delete', instance.pk),
                self.op_menu_btn and 'class="btn  btn-xs"' or '',
                self.use_menu_icon and '<i class="fa fa-trash"></i>' or '',
                self.use_menu_name and '删除' or ''))

        return ' '.join(links)

    op_link.verbose_name = '&nbsp;'
    op_link.allow_tags = True
    op_link.allow_export = False
    op_link.is_column = False

    def get_list_display(self, list_display):
        self.has_view_perm = self.view.has_permission('view')
        self.has_change_perm = self.view.has_permission('change')
        self.has_delete_perm = self.view.has_permission('delete')
        if self.use_op_menu:
            if self.has_view_perm or self.has_add_perm or self.has_change_perm:
                list_display.append('op_link')
                self.view.op_link = self.op_link
        if not self.view.pop and self.use_related_menu and len(self.get_related_list()):
            list_display.append('related_link')
            self.view.related_link = self.related_link
            self.view.get_detail_url = self.get_first_rel_url

        return list_display

    def get_first_rel_url(self, obj):
        return self.first_rel_url + str(obj.pk)


class RelateObject(object):
    '''
    列表关联的外键对象信息封装
    '''

    def __init__(self, view, lookup, value):
        self.view = view
        self.org_model = view.model
        self.opts = view.opts
        self.lookup = lookup
        self.value = value

        parts = lookup.split(LOOKUP_SEP)
        # 得到外键的字段
        field = self.opts.get_field(parts[0])

        if not hasattr(field, 'remote_field') and not isinstance(field, RelatedObject):
            raise Exception('Relate Lookup field must a related field')
        # 得到外键到的模型 to_model
        if hasattr(field, 'remote_field'):
            self.to_model = field.related_model
            self.rel_name = '__'.join(parts[1:])
            self.is_m2m = bool(field.many_to_many)
        else:
            self.to_model = field.model
            self.rel_name = self.to_model._meta.pk.name
            self.is_m2m = False
        # 得到当前外键关联的对象 to_objs
        _manager = self.to_model._default_manager
        if hasattr(_manager, 'get_query_set'):
            to_qs = _manager.get_query_set()
        else:
            to_qs = _manager.get_queryset()
        self.to_objs = to_qs.filter(**{self.rel_name: value}).all()

        self.field = field

    def filter(self, queryset):
        return queryset.filter(**{self.lookup: self.value})

    def get_title(self):
        if len(self.to_objs) == 1:
            to_model_name = str(self.to_objs[0])
        else:
            to_model_name = force_str(self.to_model._meta.verbose_name)
        return to_model_name

    def get_brand_name(self):
        to_model_name = self.get_title()
        return mark_safe("<span class='rel-brand'>%s <i class='fa fa-caret-right'></i></span> %s" % (
            to_model_name, force_str(self.opts.verbose_name_plural)))

    def get_list_tabs(self):
        _r_list = RelateMenuPlugin.get_r_list(self.to_model)
        list_tabs = []
        for r in _r_list:
            if hasattr(r, 'opts'):
                _model = r.model
            else:
                _model = r.related_model
            if _model not in list(self.view.website.modelconfigs.keys()):
                continue
            info = RelateMenuPlugin.get_r_model_info(r)
            list_url = reverse(
                '%s:%s_%s_changelist' % (self.view.website.module_name, info['label'], info['model_name']))
            r_list_url = "%s?%s=%s" % (list_url, RELATE_PREFIX + info['lookup_name'], self.to_objs[0].pk)
            list_tabs.append((r_list_url, info['verbose_name']))
        return list_tabs


class RelateDisplayPlugin(ViewPlugin):
    def init_request(self, *args, **kwargs):
        self.relate_obj = None
        for k, v in list(self.request.GET.items()):
            if smart_str(k).startswith(RELATE_PREFIX):
                self.relate_obj = RelateObject(
                    self.view, smart_str(k)[len(RELATE_PREFIX):], v)
                break
        if self.relate_obj == None:
            for k, v in list(self.request.POST.items()):
                if smart_str(k).startswith(RELATE_PREFIX):
                    self.relate_obj = RelateObject(
                        self.view, smart_str(k)[len(RELATE_PREFIX):], v)
                    break
        return bool(self.relate_obj)

    def _get_relate_params(self):
        return RELATE_PREFIX + self.relate_obj.lookup, self.relate_obj.value

    def _get_input(self):
        return '<input type="hidden" name="%s" value="%s" />' % self._get_relate_params()

    def _get_url(self, url):
        return url + ('&' if url.find('?') > 0 else '?') + ('%s=%s' % self._get_relate_params())


class ListRelateDisplayPlugin(RelateDisplayPlugin):
    '''
    列表视图增加外键信息显示
    '''

    def init_request(self, *args, **kwargs):
        ret = super(ListRelateDisplayPlugin, self).init_request(*args, **kwargs)
        if self.relate_obj:
            self.view.force_select = self.view.get_model_url(self.relate_obj.to_model, 'changelist')
        return ret

    def get_list_queryset(self, queryset):
        if self.relate_obj:
            queryset = self.relate_obj.filter(queryset)
        return queryset

    def get_object_url(self, url, result):
        return self._get_url(url)

    def get_context(self, context):
        self.view.list_template = 'website/views/model_list_rel.tpl'
        # context['brand_name'] = self.relate_obj.get_brand_name()
        context['title'] = self.relate_obj.get_title()
        context['rel_objs'] = self.relate_obj.to_objs
        if 'add_url' in context:
            context['add_url'] = self._get_url(context['add_url'])
        context['rel_detail_url'] = self.view.get_model_url(self.relate_obj.to_model, 'detail',
                                                            self.relate_obj.to_objs[0].id)
        self.view.list_tabs = self.relate_obj.get_list_tabs()
        context['cur_tab'] = int(self.request.GET.get('_tab', '0'))

        to_model = self.relate_obj.to_model
        to_objs = self.relate_obj.to_objs
        context['has_rel_change_permission'] = self.view.has_model_perm(to_model, 'change')
        context['has_rel_delete_permission'] = self.view.has_model_perm(to_model, 'delete')
        if context['has_rel_change_permission']:
            context['rel_change_url'] = self.view.get_model_url(to_model, 'change', to_objs[0].pk)
        if context['has_rel_delete_permission']:
            context['rel_delete_url'] = self.view.get_model_url(to_model, 'delete', to_objs[0].pk)

        return context

    def get_list_display(self, list_display):
        if not self.relate_obj.is_m2m:
            try:
                list_display.remove(self.relate_obj.field.name)
            except Exception:
                pass
        return list_display

    def get_breadcrumb(self, bcs):
        '''
        导航链接基础部分
        '''
        if self.website.style_fixhead:
            return []
        base = [{
            'url': self.get_site_url('index'),
            'title': _('Home')
        }]
        to_model = self.relate_obj.to_model
        model_admin = self.website.modelconfigs[to_model]
        app_label = getattr(model_admin, 'app_label', to_model._meta.app_label)
        module_mod = self.website.modules[app_label]
        base.append({
            'url': module_mod.index_url,
            'title': hasattr(module_mod, 'verbose_name') and module_mod.verbose_name or app_label
        })
        item = {}
        opts = to_model._meta
        item = {'title': opts.verbose_name_plural}
        item['url'] = self.view.get_model_url(to_model, 'changelist')
        base.append(item)

        to_objs = self.relate_obj.to_objs
        if len(to_objs) == 1:
            to_model_name = str(to_objs[0])
        else:
            to_model_name = force_str(to_model._meta.verbose_name)
        base.append({'title': to_model_name, 'url': ''})

        return base


class EditRelateDisplayPlugin(RelateDisplayPlugin):
    def get_form_datas(self, datas):
        if self.view.org_obj is None and self.view.request_method == 'get':
            datas['initial'][
                self.relate_obj.field.name] = self.relate_obj.value
        return datas

    def post_response(self, response):
        if isinstance(response, str) and response != self.get_site_url('index'):
            return self._get_url(response)
        return response

    def get_context(self, context):
        if 'delete_url' in context:
            context['delete_url'] = self._get_url(context['delete_url'])
        return context

    def block_after_fieldsets(self, context, nodes):
        return self._get_input()


class DeleteRelateDisplayPlugin(RelateDisplayPlugin):
    def post_response(self, response):
        if isinstance(response, str) and response != self.get_site_url('index'):
            return self._get_url(response)
        return response

    def block_form_fields(self, context, nodes):
        return self._get_input()


class RelateFieldPlugin(ViewPlugin):
    def get_field_style(self, attrs, db_field, style, **kwargs):
        if (style == 'fk_ajax' or style == 'fk-ajax' or style == 'fk_search') and isinstance(db_field,
                                                                                             models.ForeignKey):
            db = kwargs.get('using')
            return dict(attrs or {},
                        widget=website.views.widgets.ForeignKeySearchWidget(db_field.remote_field,
                                                                                        self.view,
                                                                                        using=db))
        if (style == 'fk_raw' or style == 'fk-raw') and isinstance(db_field, models.ForeignKey):
            db = kwargs.get('using')
            return dict(attrs or {},
                        widget=website.views.widgets.ForeignKeyRawIdWidget(db_field.remote_field, self.view,
                                                                                       using=db))
        if style == 'fk_select' and isinstance(db_field, models.ForeignKey):
            db = kwargs.get('using')
            return dict(attrs or {}, widget=website.views.widgets.SelectWidget)
        return attrs


# <editor-fold desc="多对多插件">
class M2MSelectPlugin(ViewPlugin):

    def get_field_style(self, attrs, db_field, style, **kwargs):
        if style == 'm2m_transfer' and isinstance(db_field, ManyToManyField):
            return {'widget': website.views.widgets.SelectMultipleTransfer(db_field.verbose_name, False),
                    'help_text': ''}
        if style == 'm2m_dropdown' and isinstance(db_field, ManyToManyField):
            return {'widget': website.views.widgets.SelectMultipleDropdown, 'help_text': ''}
        if style == 'm2m_select' and isinstance(db_field, ManyToManyField):
            return {'widget': website.views.widgets.AdminSelectMultiple}

        if style == 'm2m_raw' and isinstance(db_field, ManyToManyField):
            db = kwargs.get('using')
            return {'widget': website.views.widgets.ManyToManyRawIdWidget(db_field.remote_field, self.view,
                                                                                      using=db),
                    'help_text': ''}
        if style == 'm2m_ajax' and isinstance(db_field, ManyToManyField):
            return {
                'widget': website.views.widgets.SelectMultipleAjax(db_field.remote_field, self.view, False),
                'help_text': ''}
        if style == 'm2m_ajax_multi' and isinstance(db_field, ManyToManyField):
            return {
                'widget': website.views.widgets.SelectMultipleAjax(db_field.remote_field, self.view, True),
                'help_text': ''}
        if style == 'm2m_select2' and isinstance(db_field, ManyToManyField):
            return {'widget': website.views.widgets.SelectMultipleDropselect, 'help_text': ''}
        return attrs


class M2MTreePlugin(ViewPlugin):
    def init_request(self, *args, **kwargs):
        self.include_m2m_tree = False
        return hasattr(self.view, 'style_fields') and \
               ('m2m_tree' in list(self.view.style_fields.values()) or 'fk_tree' in list(
                   self.view.style_fields.values()) or 'fk_tree_leaf' in list(
                   self.view.style_fields.values()))

    def get_field_style(self, attrs, db_field, style, **kwargs):
        if style == 'm2m_tree' and isinstance(db_field, ManyToManyField):
            self.include_m2m_tree = True
            return {'form_class': ModelTreeChoiceField, 'help_text': None}
        if style == 'fk_tree' and isinstance(db_field, ForeignKey):
            self.include_m2m_tree = True
            return {'form_class': ModelTreeChoiceFieldFK, 'help_text': None}
        if style == 'fk_tree_leaf' and isinstance(db_field, ForeignKey):
            self.include_m2m_tree = True
            return {'form_class': ModelTreeChoiceFieldFKLeaf, 'help_text': None}
        return attrs

    def get_media(self, media):
        if self.include_m2m_tree:
            media += Media(js=[self.static('website/vendor/common/js/jquery.jstree.js'),
                               self.static('website/vendor/common/js/form_tree.js')])
        return media


# </editor-fold>
# </editor-fold>

# <editor-fold desc="字段排序插件">
SORTBY_VAR = '_sort_by'


class SortablePlugin(ViewPlugin):
    sortable_fields = ['sort']

    # Media
    def get_media(self, media):
        if self.sortable_fields and self.request.GET.get(SORTBY_VAR):
            media = media + self.vendor('website.plugin.sortable.js')
        return media

    # Block Views
    def block_top_toolbar(self, context, nodes):
        if self.sortable_fields:
            pass
            # current_refresh = self.request.GET.get(REFRESH_VAR)
            # context.update({
            #     'has_refresh': bool(current_refresh),
            #     'clean_refresh_url': self.view.get_query_string(remove=(REFRESH_VAR,)),
            #     'current_refresh': current_refresh,
            #     'refresh_times': [{
            #         'time': r,
            #         'url': self.view.get_query_string({REFRESH_VAR: r}),
            #         'selected': str(r) == current_refresh,
            #     } for r in self.refresh_times],
            # })
            # nodes.append(loader.render_to_string('website/blocks/refresh.tpl', context_instance=context))


# </editor-fold>

# <editor-fold desc="主题插件">
THEME_CACHE_KEY = 'base_themes'


class ThemePlugin(ViewPlugin):
    enable_themes = False
    # {'name': 'Blank Theme', 'description': '...', 'css': 'http://...', 'thumbnail': '...'}
    user_themes = None
    use_bootswatch = False
    default_theme = static('website/css/themes/bootstrap-website.css')
    bootstrap2_theme = static('website/css/themes/bootstrap-theme.css')

    def init_request(self, *args, **kwargs):
        return self.enable_themes

    def _get_theme(self):
        if self.user:
            try:
                return UserSetting.objects.get(user=self.user, key="website-theme").value
            except Exception:
                pass
        if '_theme' in self.request.COOKIES:
            return urllib.parse.unquote(self.request.COOKIES['_theme'])
        return self.default_theme

    def get_context(self, context):
        context['site_theme'] = self._get_theme()
        return context

    # Media
    def get_media(self, media):
        return media + self.vendor('jquery-ui-effect.js', 'website.plugin.themes.js')

    # Block Views
    def block_top_navmenu(self, context, nodes):

        themes = [{'name': _("Default"), 'description': _(
            "Default bootstrap theme"), 'css': self.default_theme},
                  {'name': _("Bootstrap2"), 'description': _("Bootstrap 2.x theme"),
                   'css': self.bootstrap2_theme}]
        select_css = context.get('site_theme', self.default_theme)

        if self.user_themes:
            themes.extend(self.user_themes)

        if self.use_bootswatch:
            ex_themes = cache.get(THEME_CACHE_KEY)
            if ex_themes:
                themes.extend(json.loads(ex_themes))
            else:
                ex_themes = []
                try:
                    import requests
                    watch_themes = json.loads(requests.get('http://api.bootswatch.com/3/').text)['themes']
                    ex_themes.extend([
                        {'name': t['name'], 'description': t['description'],
                         'css': t['cssMin'], 'thumbnail': t['thumbnail']}
                        for t in watch_themes if t['name'] not in ('Cosmo', 'Cyborg', 'Darkly')])
                except Exception:
                    pass

                cache.set(THEME_CACHE_KEY, json.dumps(ex_themes), 24 * 3600)
                themes.extend(ex_themes)

        nodes.append(loader.render_to_string('website/blocks/comm.top.theme.tpl',
                                             {'themes': themes, 'select_css': select_css,
                                              'head_fix': self.website.style_fixhead}))


# </editor-fold>

# <editor-fold desc="顶部搜索添加插件">
class TopNavPlugin(ViewPlugin):
    global_search_models = None
    global_add_models = None

    def get_context(self, context):
        return context

    # Block Views
    def block_top_navbar(self, context, nodes):
        search_models = []

        site_name = self.website.module_name
        if self.global_search_models == None:
            models = list(self.website.modelconfigs.keys())
        else:
            models = self.global_search_models

        for model in models:
            app_label = model._meta.app_label

            if self.has_model_perm(model, "view"):
                info = (app_label, model._meta.model_name)
                if getattr(self.website.modelconfigs[model], 'search_fields', None):
                    try:
                        search_models.append({
                            'title': _('Search %s') % capfirst(model._meta.verbose_name_plural),
                            'url': reverse('%s:%s_%s_changelist' % (self.website.namespace, *info),
                                           current_app=site_name),
                            'model': model
                        })
                    except NoReverseMatch:
                        pass

        nodes.append(loader.render_to_string('website/blocks/comm.top.topnav.tpl',
                                             {'search_models': search_models, 'search_name': SEARCH_VAR}))

    def block_top_navmenu(self, context, nodes):
        add_models = []

        site_name = self.website.module_name
        url_pre = self.website.style_fixhead and '#!' or ''

        if self.global_add_models == None:
            models = list(self.website.modelconfigs.keys())
        else:
            models = self.global_add_models
        for model in models:
            app_label = model._meta.app_label

            if self.has_model_perm(model, "add"):
                info = (app_label, model._meta.model_name)
                try:
                    add_models.append({
                        'title': _('Add %s') % capfirst(model._meta.verbose_name),
                        'url': url_pre + reverse('%s:%s_%s_add' % (self.website.namespace, *info),
                                                 current_app=site_name),
                        'model': model
                    })
                except NoReverseMatch:
                    pass

        nodes.append(
            loader.render_to_string('website/blocks/comm.top.topnav.tpl',
                                    {'add_models': add_models, 'head_fix': self.website.style_fixhead}))


# </editor-fold>

# <editor-fold desc="富文本插件">
class WYSIHtml5Plugin(ViewPlugin):
    def init_request(self, *args, **kwargs):
        self.include_html5 = False
        self.include_tinymce = False
        self.include_ckediter = False
        if hasattr(self.view, 'style_fields'):
            styles = list(self.view.style_fields.values())
            return ('wysi_html5' in styles or 'wysi_tinymce' in styles or 'wysi_ck' in styles)
        else:
            return False

    def get_field_style(self, attrs, db_field, style, **kwargs):
        if isinstance(db_field, TextField):
            if style == 'wysi_html5':
                self.include_html5 = True
                return {'widget': website.views.widgets.AdminTextareaWidget(
                    attrs={'class': 'textarea-field wysi_html5'})}
            if style == 'wysi_tinymce':
                self.include_tinymce = True
                return {'widget': website.views.widgets.AdminTextareaWidget(
                    attrs={'class': 'textarea-field wysi_tinymce'})}
            if style == 'wysi_ck':
                self.include_ckediter = True
                return {'widget': website.views.widgets.AdminTextareaWidget(
                    attrs={'class': 'textarea-field wysi_ck ckeditor'})}
        return attrs

    def get_field_result(self, result, field_name):
        if self.view.style_fields.get(field_name) in ('wysi_html5', 'wysi_tinymce', 'wysi_ck'):
            result.allow_tags = True
        return result

    # Media
    def get_media(self, media):
        if self.include_html5:
            media.add_js([self.static('website/vendor/common/js/wysihtml5-0.3.0.min.js'),
                          self.static('website/vendor/common/js/bootstrap-wysihtml5.js'),
                          self.static('website/vendor/common/js/locales/bootstrap-wysihtml5.zh-CN.js'),
                          self.static('website/vendor/common/js/form_wysi.js')])
            media.add_css({'screen': [self.static('website/vendor/common/css/wysiwyg-color.css'),
                                      self.static('website/vendor/common/css/bootstrap-wysihtml5.css')]})
        if self.include_tinymce:
            media.add_js([
                self.static('website/vendor/common/tiny_mce/jquery.tinymce.js'),
                self.static('website/vendor/common/js/form_wysi.js')])
        if self.include_ckediter:
            media += self.vendor('ckeditor.js')
        return media


# </editor-fold>

# <editor-fold desc="向导插件">
def normalize_name(name):
    new = re.sub('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))', '_\\1', name)
    return new.lower().strip('_')


class WizardFormPlugin(ViewPlugin):
    wizard_form_list = None
    wizard_for_update = False

    storage_name = 'website.tools.storage.SessionStorage'
    form_list = None
    initial_dict = None
    instance_dict = None
    condition_dict = None
    file_storage = None

    def _get_form_prefix(self, step=None):
        if step is None:
            step = self.steps.current
        return 'step_%d' % list(self.get_form_list().keys()).index(step)

    def get_form_list(self):
        if not hasattr(self, '_form_list'):
            init_form_list = SortedDict()

            assert len(
                self.wizard_form_list) > 0, 'at least one form is needed'

            for i, form in enumerate(self.wizard_form_list):
                init_form_list[str(form[0])] = form[1]

            self._form_list = init_form_list

        return self._form_list

    # ViewPlugin replace methods
    def init_request(self, *args, **kwargs):
        if self.request.is_ajax() or ("_ajax" in self.request.GET) or not hasattr(self.request, 'session') or (
                args and not self.wizard_for_update):
            # update view
            return False
        return bool(self.wizard_form_list)

    def prepare_form(self, __):
        # init storage and step helper
        self.prefix = normalize_name(self.__class__.__name__)
        self.storage = get_storage(
            self.storage_name, self.prefix, self.request,
            getattr(self, 'file_storage', None))
        self.steps = StepsHelper(self)
        self.wizard_goto_step = False

        if self.request.method == 'GET':
            self.storage.reset()
            self.storage.current_step = self.steps.first

            self.view.model_form = self.get_step_form()
        else:
            # Look for a wizard_goto_step element in the posted data which
            # contains a valid step name. If one was found, render the requested
            # form. (This makes stepping back a lot easier).
            wizard_goto_step = self.request.POST.get('wizard_goto_step', None)
            if wizard_goto_step and int(wizard_goto_step) < len(self.get_form_list()):
                self.storage.current_step = list(self.get_form_list(
                ).keys())[int(wizard_goto_step)]
                self.view.model_form = self.get_step_form()
                self.wizard_goto_step = True
                return

            # Check if form was refreshed
            management_form = ManagementForm(
                self.request.POST, prefix=self.prefix)
            if not management_form.is_valid():
                raise ValidationError(
                    'ManagementForm data is missing or has been tampered.')

            form_current_step = management_form.cleaned_data['current_step']
            if (form_current_step != self.steps.current and
                    self.storage.current_step is not None):
                # form refreshed, change current step
                self.storage.current_step = form_current_step

            # get the form for the current step
            self.view.model_form = self.get_step_form()

    def get_form_layout(self, __):
        attrs = self.get_form_list()[self.steps.current]
        if type(attrs) is dict and 'layout' in attrs:
            self.view.form_layout = attrs['layout']
        else:
            self.view.form_layout = None
        return __()

    def get_step_form(self, step=None):
        if step is None:
            step = self.steps.current
        attrs = self.get_form_list()[step]
        if type(attrs) in (list, tuple):
            return modelform_factory(self.model, form=forms.ModelForm,
                                     fields=attrs, formfield_callback=self.view.formfield_for_dbfield)
        elif type(attrs) is dict:
            if attrs.get('fields', None):
                return modelform_factory(self.model, form=forms.ModelForm,
                                         fields=attrs['fields'], formfield_callback=self.view.formfield_for_dbfield)
            if attrs.get('callback', None):
                callback = attrs['callback']
                if callable(callback):
                    return callback(self)
                elif hasattr(self.view, str(callback)):
                    return getattr(self.view, str(callback))(self)
        elif issubclass(attrs, forms.BaseForm):
            return attrs
        return None

    def get_step_form_obj(self, step=None):
        if step is None:
            step = self.steps.current
        form = self.get_step_form(step)
        return form(prefix=self._get_form_prefix(step),
                    data=self.storage.get_step_data(step),
                    files=self.storage.get_step_files(step))

    def get_form_datas(self, datas):
        datas['prefix'] = self._get_form_prefix()
        if self.request.method == 'POST' and self.wizard_goto_step:
            datas.update({
                'data': self.storage.get_step_data(self.steps.current),
                'files': self.storage.get_step_files(self.steps.current)
            })
        return datas

    def valid_forms(self, __):
        if self.wizard_goto_step:
            # goto get_response directly
            return False
        return __()

    def _done(self):
        cleaned_data = self.get_all_cleaned_data()
        exclude = self.view.exclude

        opts = self.view.opts
        instance = self.view.org_obj or self.view.model()

        file_field_list = []
        for f in opts.fields:
            if not f.editable or isinstance(f, models.AutoField) \
                    or not f.name in cleaned_data:
                continue
            if exclude and f.name in exclude:
                continue
            # Defer saving file-type fields until after the other fields, so a
            # callable upload_to can use the values from other fields.
            if isinstance(f, models.FileField):
                file_field_list.append(f)
            else:
                f.save_form_data(instance, cleaned_data[f.name])

        for f in file_field_list:
            f.save_form_data(instance, cleaned_data[f.name])

        instance.save()

        for f in opts.many_to_many:
            if f.name in cleaned_data:
                f.save_form_data(instance, cleaned_data[f.name])

        self.view.new_obj = instance

    def save_forms(self, __):
        # if the form is valid, store the cleaned data and files.
        form_obj = self.view.form_obj
        self.storage.set_step_data(self.steps.current, form_obj.data)
        self.storage.set_step_files(self.steps.current, form_obj.files)

        # check if the current step is the last step
        if self.steps.current == self.steps.last:
            # no more steps, render done view
            return self._done()

    def save_models(self, __):
        pass

    def save_related(self, __):
        pass

    def get_context(self, context):
        context.update({
            "show_save": False,
            "show_save_as_new": False,
            "show_save_and_add_another": False,
            "show_save_and_continue": False,
        })
        return context

    def get_response(self, response):
        self.storage.update_response(response)
        return response

    def post_response(self, __):
        if self.steps.current == self.steps.last:
            self.storage.reset()
            return __()

        # change the stored current step
        self.storage.current_step = self.steps.next

        self.view.form_obj = self.get_step_form_obj()
        self.view.setup_forms()

        return self.view.get_response()

    def get_all_cleaned_data(self):
        """
        Returns a merged dictionary of all step cleaned_data dictionaries.
        If a step contains a `FormSet`, the key will be prefixed with formset
        and contain a list of the formset cleaned_data dictionaries.
        """
        cleaned_data = {}
        for form_key, attrs in list(self.get_form_list().items()):
            form_obj = self.get_step_form_obj(form_key)
            if form_obj.is_valid():
                if type(attrs) is dict and 'convert' in attrs:
                    callback = attrs['convert']
                    if callable(callback):
                        callback(self, cleaned_data, form_obj)
                    elif hasattr(self.view, str(callback)):
                        getattr(self.view,
                                str(callback))(self, cleaned_data, form_obj)
                elif isinstance(form_obj.cleaned_data, (tuple, list)):
                    cleaned_data.update({
                        'formset-%s' % form_key: form_obj.cleaned_data
                    })
                else:
                    cleaned_data.update(form_obj.cleaned_data)
        return cleaned_data

    def get_cleaned_data_for_step(self, step):
        """
        Returns the cleaned data for a given `step`. Before returning the
        cleaned data, the stored values are being revalidated through the
        form. If the data doesn't validate, None will be returned.
        """
        if step in self.get_form_list():
            form_obj = self.get_step_form_obj(step)
            if form_obj.is_valid():
                return form_obj.cleaned_data
        return None

    def get_next_step(self, step=None):
        """
        Returns the next step after the given `step`. If no more steps are
        available, None will be returned. If the `step` argument is None, the
        current step will be determined automatically.
        """
        if step is None:
            step = self.steps.current
        form_list = self.get_form_list()
        key = form_list.keyOrder.index(step) + 1
        if len(form_list.keyOrder) > key:
            return form_list.keyOrder[key]
        return None

    def get_prev_step(self, step=None):
        """
        Returns the previous step before the given `step`. If there are no
        steps available, None will be returned. If the `step` argument is
        None, the current step will be determined automatically.
        """
        if step is None:
            step = self.steps.current
        form_list = self.get_form_list()
        key = form_list.keyOrder.index(step) - 1
        if key >= 0:
            return form_list.keyOrder[key]
        return None

    def get_step_index(self, step=None):
        """
        Returns the index for the given `step` name. If no step is given,
        the current step will be used to get the index.
        """
        if step is None:
            step = self.steps.current
        return self.get_form_list().keyOrder.index(step)

    def block_before_fieldsets(self, context, nodes):
        context.update(dict(self.storage.extra_data))
        context['wizard'] = {
            'steps': self.steps,
            'management_form': ManagementForm(prefix=self.prefix, initial={
                'current_step': self.steps.current,
            }),
        }
        nodes.append(
            dutils.render_to_string('website/blocks/model_form.before_fieldsets.wizard.tpl', context_instance=context))

    def block_submit_line(self, context, nodes):
        context.update(dict(self.storage.extra_data))
        context['wizard'] = {
            'steps': self.steps
        }
        nodes.append(
            dutils.render_to_string('website/blocks/model_form.submit_line.wizard.tpl', context_instance=context))
# </editor-fold>
