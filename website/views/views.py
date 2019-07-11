import copy
import functools
import inspect
import json
import pickle
import re
import time
import urllib.parse
from functools import update_wrapper
from urllib.parse import unquote

import django.contrib
from website.views import configs
import website.views.widgets
from django import forms, template
from django.contrib import messages
from django.contrib.auth.forms import AdminPasswordChangeForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm, \
    UserCreationForm, UserChangeForm
from django.contrib.auth.tokens import default_token_generator
from website import models
from website.tools.storage import NoFileStorageConfigured, get_storage
from website.tools.types import SortedDict
from website.views import widgets, configs
from website.views.forms import AdminAuthenticationForm, componentmanager, WidgetDataError, ManagementForm
from website.models import UserSetting, Viewmark
from website.views.fields import FakeMethodField, ShowField, ResultField, replace_field_to_value, \
    ReadOnlyField, DeleteField, Fieldset, PermissionModelMultipleChoiceField
from website.views.fieldsets import Row, Col, Main, Side, Container
from website.views.configs import EMPTY_CHANGELIST_VALUE, SEARCH_VAR, \
    TO_FIELD_VAR, ACTION_CHECKBOX_NAME, ALL_VAR, ORDER_VAR, PAGE_VAR, COL_LIST_VAR, ERROR_FLAG, ROOT_PATH_NAME, \
    BATCH_CHECKBOX_NAME, DOT, ACTION_NAME
from website.tools import dutils
from website.tools.dutils import JsonErrorDict, JSONEncoder
from website.views.utils import model_ngettext, get_deleted_objects, unquote, label_for_field, lookup_field, \
    boolean_icon, display_for_field, vendor, User, csrf_protect_m, JSONEncoder
from website.views.widgets import ChangeFieldWidgetWrapper, WidgetTypeSelect
from django.core.files.storage import default_storage
from django.core.paginator import Paginator, Page, InvalidPage
from django.db.models import Q
from django.forms import modelform_factory, formsets, BaseInlineFormSet, inlineformset_factory, HiddenInput
from django.forms.forms import DeclarativeFieldsMetaclass
from django.forms.formsets import DELETION_FIELD_NAME
from django.shortcuts import redirect, render_to_response
from django.template import RequestContext, Context, Template
from django.templatetags.static import static
from django.urls import reverse
from django.utils import six
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.html import escape, format_html, conditional_escape
from django.utils.http import urlquote, urlencode
from django.utils.itercompat import is_iterable
from django.utils.text import capfirst, Truncator
from django.contrib.auth import REDIRECT_FIELD_NAME,login, logout
from django.contrib.contenttypes.models import ContentType
from crispy_forms.bootstrap import TabHolder
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Column
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError, ObjectDoesNotExist
from django.db import router, models
from django.http import HttpResponse, HttpResponseRedirect, Http404, HttpResponseNotFound
from django.template.response import TemplateResponse, SimpleTemplateResponse
from django.utils.decorators import classonlymethod, method_decorator
from django.utils.encoding import force_str, force_text, smart_str
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _, ugettext as _, ugettext_lazy as _, ugettext_lazy
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView
from website.models import UserComponent
from website.views.fields import TDField


class IncorrectPluginArg(Exception):
    """ 当插件的方法参数错误时抛出该异常 """
    pass


"""
插件方法的__参数表示插件方法先执行
如果插件方法只有self一个参数，则先执行视图函数，必须没有返回值；否则，插件函数第二个参数是__

插件api：
  本体：
    init_request -> 返回True则表示加载自己，否则不加载
    同名函数参数设定 -> 
    
执行流：递归函数链（视图方法+插件同名方法）-> 
"""
"""
首先将实例的 plugins 属性取出，取出含有同样方法名的插件

按照插件方法的 priority 属性排序

顺序执行插件方法，执行插件方法的规则:

如果插件方法没有参数，AdminView 方法的返回结果不为空则抛出异常

如果插件方法的第一个参数为 __ ，则 AdminView 方法将作为第一个参数传入，注意，这时还未执行该方法， 在插件中可以通过 __() 执行，这样就可以实现插件在 AdminView 方法执行前实现一些自己的逻辑，例如:

def get_context(self, __):
    c = {'key': 'value'}
    c.update(__())
    return c
如果插件方法的第一个参数不为 __ ，则执行 AdminView 方法，将结果作为第一个参数传入
"""


def execfunchain(pluginfuns, lenth, fun, *args, **kwargs):
    if lenth == -1:
        return fun()
    else:
        def execfun():
            pf = pluginfuns[lenth]
            fargs = inspect.getfullargspec(pf)[0]
            if len(fargs) == 1:
                result = fun()
                if result is None:
                    return pf()
                else:
                    raise IncorrectPluginArg('ViewPlugin filter method need a arg to receive parent method result.')
            else:
                return pf(fun if fargs[1] == '__' else fun(), *args, **kwargs)

        return execfunchain(pluginfuns, lenth - 1, execfun, *args, **kwargs)


def pluginhook(fun):
    fun.__doc__ = "``filter_hook``\n\n" + (fun.__doc__ or "")

    @functools.wraps(fun)
    def filter(self, *args, **kwargs):

        def cf():
            return fun(self, *args, **kwargs)

        if self.plugins:
            plugin = []
            for a in self.plugins:
                pn = getattr(a, fun.__name__, None)
                if callable(pn):
                    pr = getattr(pn, 'priority', 10)
                    plugin.append((pr, pn))

            pns = [pn for pr, pn in sorted(plugin, key=lambda x: x[0])]
            return execfunchain(pns, len(pns) - 1, cf, *args, **kwargs)
        else:
            return cf()

    return filter


class ViewUtilMixin:
    def getviewclass(self, rview, config=None, *args, **kwargs):

        opts = kwargs.pop('opts', {})
        return self.website.createviewclass(rview, config, **opts)(self.request, *args, **kwargs)

    def getmodelviewclass(self, rview, model, *args, **kwargs):
        return self.getviewclass(rview, self.website.modelconfigs.get(model), *args, **kwargs)

    def get_site_url(self, name, *args, **kwargs):
        """
        路径工具函数
        通过 name 取得 url，会加上 Website.module_name 的 url namespace
        """
        return reverse('%s:%s' % (self.website.module_name, name), args=args, kwargs=kwargs)

    def get_model_url(self, model, name, *args, **kwargs):
        """
        name  为 add、changelist
        """
        return self.website.get_model_url(model, name, *args, **kwargs)

    def get_model_perm(self, model, name):
        return '%s.%s_%s' % (model._meta.app_label, name, model._meta.model_name)

    def has_model_perm(self, model, name, user=None):
        """
        name  为 view、change
        """
        user = user or self.user
        return user.has_perm(self.get_model_perm(model, name)) or (
                name == 'view' and self.has_model_perm(model, 'change', user))

    ########################################## HTTP 相关的函数 ##########################################
    def get_query_string(self, new_params=None, remove=None):
        """
        URL 参数控制
        在当前的query_string基础上生成新的query_string

        :param new_params: 要新加的参数，该参数为 dict
        :param remove: 要删除的参数，该参数为 list, tuple
        """
        if new_params is None:
            new_params = {}
        if remove is None:
            remove = []
        p = dict(self.request.GET.items()).copy()
        for r in remove:
            for k in [i for i in p.keys()]:
                if k.startswith(r):
                    del p[k]
        for k, v in new_params.items():
            if v is None:
                if k in p:
                    del p[k]
            else:
                p[k] = v
        return '?%s' % urlencode(p)

    def get_form_params(self, new_params=None, remove=None):
        """
        Form 参数控制
        将当前 request 的参数，新加或是删除后，生成 hidden input。用于放入 HTML 的 Form 中。

        :param new_params: 要新加的参数，该参数为 dict
        :param remove: 要删除的参数，该参数为 list, tuple
        """
        if new_params is None:
            new_params = {}
        if remove is None:
            remove = []
        p = dict(self.request.GET.items()).copy()
        for r in remove:
            for k in [i for i in p.keys()]:
                if k.startswith(r) and k != 'pop':
                    del p[k]
        for k, v in new_params.items():
            if v is None:
                if k in p:
                    del p[k]
            else:
                p[k] = v
        return mark_safe(''.join(
            '<input type="hidden" name="%s" value="%s"/>' % (k, v) for k, v in p.items() if v))

    def get_param(self, k):
        ret = self.request.GET.get(k, None)
        if ret:
            return ret
        else:
            return self.request.POST.get(k, None)

    def param_list(self):
        keys = []
        if self.request.GET:
            keys = sorted(self.request.GET.keys())
        if self.request.POST:
            keys += sorted(self.request.POST.keys())
        return keys

    ########################################## 页面Page 相关的函数 ##########################################
    def render_response(self, content, response_type='json'):
        """
        请求返回API
        便捷方法，方便生成 HttpResponse，如果 response_type 为 ``json`` 会自动转为 json 格式后输出
        """
        if response_type == 'json':
            response = HttpResponse(content_type='application/json; charset=UTF-8')
            response.write(
                json.dumps(content, cls=JSONEncoder, ensure_ascii=False))
            return response
        return HttpResponse(content)

    def render_json(self, content):
        response = HttpResponse(content_type='application/json; charset=UTF-8')
        response.write(
            json.dumps(content, cls=JSONEncoder, ensure_ascii=False))
        return response

    def render_text(self, content):
        return HttpResponse(content)

    def template_response(self, template, context):
        return self.render_tpl(template, context)

    def render_tpl(self, tpl, context):
        context.update({'current_app': self.website.module_name})
        return TemplateResponse(self.request, tpl, context)

    def message_user(self, message, level='info'):
        """
        debug error info success warning
        posts a message using the django.contrib.messages backend.
        """
        if hasattr(messages, level) and callable(getattr(messages, level)):
            getattr(messages, level)(self.request, message)

    def msg(self, message, level='info'):
        '''
        level 为 info、success、error
        '''
        self.message_user(message, level)

    def static(self, path):
        """
        路径工具函数
        :meth:`website.util.static` 的快捷方法，返回静态文件的 url。
        """
        return static(path)

    def vendor(self, *tags):
        return vendor(*tags)

    ########################################## 日志操作相关的函数 ##########################################
    def log_change(self, obj, message):
        """
        写对象日志
        """
        from django.contrib.baseadmin.models import CHANGE
        from django.contrib.contenttypes.models import ContentType
        from django.utils.encoding import force_text
        type_id = ContentType.objects.get_for_model(obj).pk
        obj_id = obj.pk
        obj_des = force_text(obj)
        aciton_id = CHANGE
        self._log(type_id, obj_id, obj_des, aciton_id, message)

    def _log(self, type_id, obj_id, obj_des, aciton_id, msg=''):
        from django.contrib.baseadmin.models import LogEntry
        LogEntry.objects.log_action(
            user_id=self.request.user.pk,
            content_type_id=type_id,
            object_id=obj_id,
            object_repr=obj_des,
            action_flag=aciton_id,
            change_message=msg
        )


class ViewConfigMixin:
    # @ Menu
    use_related_menu = True  # 列表页 是否显示模型的关联对象菜单，默认是
    menu_icon = 'fa fa-circle-o'
    use_op_menu = True  # 列表页 是否显示查看、修改、删除等操作的链接，默认是
    order = 10  # 菜单排序
    group_order = 10
    menu_group = ''  # 所属菜单组
    menu_show = True
    menu_name = ''
    perm = None
    exclude_plugins = []
    # @ Inlines
    inlines = []
    extra = 1
    style = 'tab'  # accordion(可折叠的) table（表格，效果最佳） stacked（完全平铺的，宏观效果不好） one(只显示一个) new（完全不可用）  tab（功能不能用）  gather（聚合，效果不佳）

    # @ List
    list_display = ('__str__',)  #: 显示的所有列表字段
    list_exclude = ()  #: 排除显示的列
    list_display_links = ()  #: 链接字段
    list_display_links_details = True  #: 链接到详情页面而非编辑页
    list_select_related = None  #: 是否提前加载关联数据
    list_per_page = 30  #: 每页数
    list_max_show_all = 200  #: 当点“显示全部”每页显示的最大条数
    ordering = None  #: 默认的数据排序
    list_template = None  #: 显示数据的模板 默认为 views/grid.html
    pop = False  # 是否为弹窗页
    list_tabs = []  # 列表页tab配置 【（view，url），】
    grid_layouts = ['table', 'thumbnails']  # 列表页使用的视图模式，内置表格模式（table）、看板模式（thumbnails）两种
    col_ctrl = True  # 列显示定制
    actions = []
    can_select_all = True
    can_select = True
    can_delete_multi = True
    show_viewmarks = True
    aggregate_fields = {}
    list_editable = []

    # @ filter
    search_sphinx_ins = None  # 使用的queryset
    list_filter = []  # MyFilter为自定义过滤器
    filter_grid_left = False  # 是否开启列表页左侧过滤导航功能，默认为关闭
    filter_list_position: str = ''  # lift、top
    filter_default_list = []  # 指定哪些过滤字段用于左侧导航，必须为 list_filter 的子集，注意 显示在左侧导航的过滤字段不再显示在下拉过滤器中
    search_fields = []  # 列表页搜索框可用于模糊匹配的字段

    # @ edit
    # relfield_style = 'fk-ajax'  #: 当 Model 是其他 Model 的 ref model 时，其他 Model 在显示本 Model 的字段时使用的 Field Style
    readonly_fields = ()  #: 只读的字段，这些字段不能被编辑
    fields = []  # 表单页 form中展现 包含哪些字段
    exclude = []  # 表单页 form中展现 排除哪些字段
    add_form_template = None  # 添加页面使用的模板 默认为 xadmin/views/model_form.html
    change_form_template = None  # 修改页面使用的模板 默认为 xadmin/views/model_form.html
    include_image = False  # 编辑页表单是否包含图片字段，为True时会添加一些和图片上传相关的静态文件引用
    style_fields = {}  # 'content': 'wysi_ck', 'categories': 'm2m_tree'
    remove_permissions = []  # 在管理界面上禁用的功能 默认为空 可选项 'view', 'add', 'change', 'delete'
    user_can_access_owned_objects_only = False  # 是否只能查看自己创建的对象 默认为False （用在 ModelPermissionPlugin 中，作用于列表视图）
    user_owned_objects_field = 'user'  # 用于判断是否自己创建对象的依据字段 默认 'user'（用在 ModelPermissionPlugin 中，作用于列表视图）
    user_fields = []  # 自动填充为当前用户的字段 （用在 UserFieldPlugin 中，作用于表单视图）
    log = False  # 模型对象的变动是否自动生成日志记录，默认为不自动生成，置为True即可开启


class ViewTemplate(ViewUtilMixin, View):
    base_template = 'website/base.tpl'
    need_login_permission = True
    csrf = True

    @classonlymethod
    def as_view(cls):
        def view(request, *args, **kwargs):
            self = cls(request, *args, **kwargs)  # call __init__

            if hasattr(self, 'get') and not hasattr(self, 'head'):
                self.head = self.get

            if self.request_method in self.http_method_names:
                handler = getattr(
                    self, self.request_method, self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed

            return handler(request, *args, **kwargs)

        update_wrapper(view, cls, updated=())
        view.need_login_permission = cls.need_login_permission
        view.login_view = getattr(cls, 'login_view', None)
        if not cls.csrf:
            view.csrf_exempt = True
        return view

    def __init__(self, request, *args, **kwargs):
        self.request = request
        self.request_method = request.method.lower()
        self.user = request.user
        self.plugins = [p(self) for p in self.pluginclasses]
        self.args = args
        self.kwargs = kwargs
        self.init_plugin(*args, **kwargs)
        self.init_request(*args, **kwargs)

    def init_request(self, *args, **kwargs):
        pass

    def init_plugin(self, *args, **kwargs):
        plugins = []
        for a in self.plugins:
            a.request = self.request
            a.user = self.user
            a.args = self.args
            a.kwargs = self.kwargs
            can = a.init_request(*args, **kwargs)
            if can is not False:
                plugins.append(a)
        self.plugins = plugins

    @pluginhook
    def get_context(self):
        """
        返回显示页面所需的 context 对象。
        """
        return {'cl': self, 'media': self.media, 'base_template': self.base_template, 'website': self.website}

    @property
    def media(self):
        return self.get_media()

    @pluginhook
    def get_media(self):
        """
        取得页面所需的 Media 对象，用于生成 css 和 js 文件
        """
        return forms.Media()


class LayoutViewTemplate(ViewTemplate, ViewConfigMixin):
    base_template = 'website/adminlte.tpl'
    force_select = None
    perm = None

    def _check_menu_permission(self, node):
        need_perm = getattr(node, 'perm', None)
        if need_perm is None:
            return True
        elif callable(need_perm):
            return need_perm(self.user)
        elif need_perm == 'super':  # perm项如果为 super 说明需要超级用户权限
            return self.user.is_superuser
        else:
            return self.user.has_perm(need_perm)

    def get_nav_menu(self, app_label=None):
        from website.tools.types import tree
        if self.website.style_adminlte:
            app_label = None
        menu_session_key = app_label and 'nav_menu_%s' % app_label or 'nav_menu'
        nav_menu = tree()
        if not settings.DEBUG and menu_session_key in self.request.session:
            nav_menu = json.loads(self.request.session[menu_session_key])
        else:
            menutree = copy.deepcopy(self.website.menus)
            nav_menu = {'data': {}, 'branch': [], 'leaf': []}
            nav_menu['branch'] = menutree[0]['branch']
            nav_menu['leaf'] = menutree[0]['leaf']

            def deep(i, nav_menu):
                for l in menutree[i]['branch']:
                    for r in nav_menu['branch']:
                        if l['up'] == r['data']['title']:
                            if type(r['branch']) != list:
                                r['branch'] = []
                            r['branch'].append(l)
                    i += 1
                    deep(i, nav_menu['branch'])

            deep(1, nav_menu)
        return nav_menu

    def get_select_menu(self):
        if hasattr(self, 'app_label'):
            menus = self.website.get_select_menu(self.app_label)
            return menus
        else:
            return []

    def deal_selected(self, nav_menu):
        def deep(menu):
            for l in menu['leaf']:
                base_url = ''
                chop_index = l['url'].find('?')
                if chop_index == -1:
                    base_url = l['url']
                else:
                    base_url = l['url'][:chop_index]
                path = self.force_select or self.request.path
                selected = path.startswith(base_url)
                if selected:
                    l['selected'] = True
                    # print('选中的叶子：',l['title'])
                    menu['data']['selected'] = True
                    # print('选中的枝：', menu['data']['title'])
                    # print('预计上级枝：', menu['up'])
                    if 'up' in menu and menu['up'] != '':
                        for b in nav_menu['branch']:
                            # print('顶级枝:', b['data']['title'])
                            if menu['up'] == b['data']['title']:
                                # print('命中枝：', b['data']['title'])
                                b['data']['selected'] = True
                                break
                    return True
            for b in menu['branch']:
                base_url = ''
                chop_index = b['data']['url'].find('?')
                if chop_index == -1:
                    base_url = b['data']['url']
                else:
                    base_url = b['data']['url'][:chop_index]
                path = self.force_select or self.request.path
                selected = path.startswith(base_url)
                if selected:
                    b['data']['selected'] = True
                deep(b)

        deep(nav_menu)

        # print(json.dumps(nav_menu,ensure_ascii=False))

    @pluginhook
    def get_context(self):
        context = super(LayoutViewTemplate, self).get_context()

        nav_menu = []
        if '_pop' not in self.request.GET:
            _module_label = hasattr(self, 'app_label') and self.app_label or None
            nav_menu = self.get_nav_menu(_module_label)
            self.deal_selected(nav_menu)

        if self.website.style_adminlte: self.website.style_menu = 'ext'
        context.update({
            'menu_template': configs.BUILDIN_STYLES.get(self.website.style_menu, configs.BUILDIN_STYLES[
                'default']),
            'nav_menu': nav_menu,
            'site_menu': self.get_select_menu(),
            'site_title': self.website.style_title,
            'site_footer': self.website.style_footer,
            'head_fix': self.website.style_fixhead,
            'adminlte': self.website.style_adminlte,
            'base_template': self.base_template,
        })

        return context

    @pluginhook
    def get_menu_icon(self, model):
        icon = None
        if model in self.website.modelconfigs:
            # 如果 Model 的 iview 中有 menu_icon 属性，则使用该属性
            icon = self.website.modelconfigs[model].menu_icon
        return icon

    def block_top_account_menu(self, context, nodes):
        a_class = self.website.style_fixhead and 'class="J_menuItem"' or ''
        url_pre = self.website.style_fixhead and '#!' or ''
        return '<li><a %s href="%s"><i class="fa fa-key"></i> %s</a></li>' % (
            a_class, url_pre + self.get_site_url('account_password'), _('Change Password'))

    @pluginhook
    def get_breadcrumb(self):
        if self.website.style_fixhead:
            return []
        base = [{
            'url': self.get_site_url('index'),
            'title': _('Home')
        }]
        if hasattr(self, 'app_label') and self.app_label:
            module_mod = self.website.modules[self.app_label]
            base.append({
                'url': module_mod.index_url,
                'title': hasattr(module_mod, 'verbose_name') and module_mod.verbose_name or self.app_label
            })
        return base

    def get(self, r):
        return self.render_tpl(self.base_template, self.get_context())


class ModelViewTemplate(LayoutViewTemplate):
    model = None
    form_layout = None

    def __init__(self, request, *args, **kwargs):
        self.opts = self.model._meta
        self.app_label = self.model._meta.app_label
        self.model_name = self.model._meta.model_name
        self.model_info = (self.model._meta.app_label, self.model_name)

        super(ModelViewTemplate, self).__init__(request, *args, **kwargs)

    @pluginhook
    def get_context(self):
        new_context = {
            "opts": self.opts,
            "app_label": self.app_label,
            "model_name": self.model_name,
            "verbose_name": force_str(self.opts.verbose_name),
            'menu_icon': self.get_menu_icon(self.model),
        }
        context = super(ModelViewTemplate, self).get_context()
        context.update(new_context)
        return context

    @pluginhook
    def get_breadcrumb(self):
        '''
        导航链接基础部分
        '''
        bcs = super(ModelViewTemplate, self).get_breadcrumb()
        item = {'title': self.opts.verbose_name_plural}
        if self.has_view_permission():
            item['url'] = self.model_admin_url('changelist')
        bcs.append(item)
        return bcs

    @pluginhook
    def get_object(self, object_id):
        """
        根据 object_id 获得唯一的 Model 实例
        """
        queryset = self.queryset()
        model = queryset.model
        try:
            object_id = model._meta.pk.to_python(object_id)
            return queryset.get(pk=object_id)
        except (model.DoesNotExist, ValidationError):
            return None

    @pluginhook
    def get_object_url(self, obj):
        if self.has_change_permission(obj):
            return self.model_admin_url("change", getattr(obj, self.opts.pk.attname))
        elif self.has_view_permission(obj):
            return self.model_admin_url("detail", getattr(obj, self.opts.pk.attname))
        else:
            return None

    def model_admin_url(self, name, *args, **kwargs):
        return reverse(
            "%s:%s_%s_%s" % (self.website.module_name, self.opts.app_label,
                             self.model_name, name), args=args, kwargs=kwargs)

    def get_model_url(self, model, name, *args, **kwargs):
        opts = model._meta
        return reverse(
            "%s:%s_%s_%s" % (self.website.module_name, opts.app_label,
                             opts.model_name, name), args=args, kwargs=kwargs)

    def get_template_list(self, template_name):
        opts = self.opts
        return (
            "website/%s/%s/%s" % (opts.app_label, opts.object_name.lower(), template_name),
            "website/%s/%s" % (opts.app_label, template_name),
            "website/%s" % template_name,
        )

    def get_ordering(self):
        return self.ordering or ()

    @pluginhook
    def queryset(self):
        """
        模型的默认数据集
        """
        _manager = self.model._default_manager
        if hasattr(_manager, 'get_query_set'):
            return _manager.get_query_set()
        else:
            return _manager.get_queryset()

    def has_view_permission(self, obj=None):
        return ('view' not in self.remove_permissions) and (
                self.user.has_perm('%s.view_%s' % self.model_info) or self.user.has_perm(
            '%s.change_%s' % self.model_info))

    def has_add_permission(self):
        return ('add' not in self.remove_permissions) and self.user.has_perm('%s.add_%s' % self.model_info)

    def has_change_permission(self, obj=None):
        return ('change' not in self.remove_permissions) and self.user.has_perm('%s.change_%s' % self.model_info)

    def has_delete_permission(self, obj=None):
        return ('delete' not in self.remove_permissions) and self.user.has_perm('%s.delete_%s' % self.model_info)

    def has_permission(self, perm_code):
        raw_code = perm_code[:]
        if perm_code in ('view', 'add', 'change', 'delete'):
            perm_code = '%s.%s_%s' % (self.model._meta.app_label, perm_code, self.model_name)
        return (raw_code not in self.remove_permissions) and self.user.has_perm(perm_code)

    def has_model_permission(self, model, perm_code):
        opts = model._meta
        raw_code = perm_code[:]
        if perm_code in ('view', 'add', 'change', 'delete'):
            perm_code = '%s.%s_%s' % (opts.app_label, perm_code, opts.model_name)
        return (raw_code not in self.remove_permissions) and self.user.has_perm(perm_code)

    def get_model_perms(self):
        return {
            'view': self.has_view_permission(),
            'add': self.has_add_permission(),
            'change': self.has_change_permission(),
            'delete': self.has_delete_permission(),
        }

    @property
    def pk_name(self):
        return self.opts.pk.attname


FORMFIELD_FOR_DBFIELD_DEFAULTS = {
    models.DateTimeField: {'form_class': forms.SplitDateTimeField, 'widget': widgets.SplitDateTime},
    models.DateField: {'widget': widgets.DateWidget},
    models.TimeField: {'widget': widgets.TimeWidget},
    models.TextField: {'widget': widgets.AdminTextareaWidget},
    models.URLField: {'widget': widgets.AdminURLFieldWidget},
    models.IntegerField: {'widget': widgets.AdminIntegerFieldWidget},
    models.BigIntegerField: {'widget': widgets.AdminIntegerFieldWidget},
    models.CharField: {'widget': widgets.AdminTextInputWidget},
    models.IPAddressField: {'widget': widgets.AdminTextInputWidget},
    models.ImageField: {'widget': widgets.AdminFileWidget},
    models.FileField: {'widget': widgets.AdminFileWidget},
    models.ForeignKey: {'widget': widgets.SelectWidget},
    models.OneToOneField: {'widget': widgets.SelectWidget},
}
DEFAULT_RELFIELD_STYLE = {
    'fk': 'fk_select',
    'm2m': 'm2m_transfer'
}


class ModelFormViewTemplate(ModelViewTemplate):
    form = forms.ModelForm  # 由 Model 生成 Form 的基类，默认为 django.forms.ModelForm

    formfield_overrides = {}  # 可以指定某种类型的 DB Field，使用指定的FormField的属性

    save_as = False  #: 是否显示 ``另存为`` 按钮
    save_on_top = False  #: 是否在页面上面显示按钮组
    grid = False
    hide_other_field = False
    add_redirect_url = None
    edit_redirect_url = None

    def __init__(self, request, *args, **kwargs):
        overrides = FORMFIELD_FOR_DBFIELD_DEFAULTS.copy()
        overrides.update(self.formfield_overrides)
        self.formfield_overrides = overrides
        super(ModelFormViewTemplate, self).__init__(request, *args, **kwargs)

    def init_request(self, obj=None):
        self.org_obj = obj
        self.prepare_form()
        self.instance_forms()

    @pluginhook
    def get_form_datas(self):
        return {'instance': self.org_obj}

    @pluginhook
    def formfield_for_dbfield(self, db_field, **kwargs):
        if isinstance(db_field, models.ManyToManyField) and not db_field.remote_field.through._meta.auto_created:
            return None
        # print('db_field:', db_field)
        attrs = self.get_field_attrs(db_field, **kwargs)
        return db_field.formfield(**dict(attrs, **kwargs))

    @pluginhook
    def get_field_attrs(self, db_field, **kwargs):

        if db_field.name in self.style_fields:
            # 如果设置了 Field Style，则返回 Style 的属性
            attrs = self.get_field_style(db_field, self.style_fields[db_field.name], **kwargs)
            if attrs:
                return attrs

        if hasattr(db_field, "remote_field") and db_field.remote_field:
            related_modeladmin = self.website.modelconfigs.get(db_field.remote_field.model)
            if related_modeladmin and hasattr(related_modeladmin, 'relfield_style'):
                attrs = self.get_field_style(db_field, related_modeladmin.relfield_style, **kwargs)
                if attrs:
                    return attrs
            if isinstance(db_field, models.ForeignKey):
                _style = DEFAULT_RELFIELD_STYLE.get('fk', '')
            elif isinstance(db_field, models.ManyToManyField):
                _style = DEFAULT_RELFIELD_STYLE.get('m2m', '')
            if _style:
                attrs = self.get_field_style(db_field, _style, **kwargs)
                if attrs:
                    return attrs

        if db_field.choices:
            return {'widget': website.views.widgets.SelectWidget}

        for klass in db_field.__class__.mro():  # 循环类及基类
            if klass in self.formfield_overrides:
                return self.formfield_overrides[klass].copy()

        return {}

    @pluginhook
    def get_field_style(self, db_field, style, **kwargs):
        """
        根据 FieldStyle 返回 FormField 属性。扩展插件可以过滤该方法，提供各种不同的 Style
        """
        if style in ('radio', 'radio-inline') and (db_field.choices or isinstance(db_field, models.ForeignKey)):
            # fk 字段生成 radio 表单控件
            attrs = {
                'widget': website.views.widgets.AdminRadioSelect(attrs={'inline': style == 'radio-inline'})}
            if db_field.choices:
                attrs['choices'] = db_field.get_choices(include_blank=db_field.blank, blank_choice=[('', _('Null'))])
            return attrs

        if style in ('checkbox', 'checkbox-inline') and isinstance(db_field, models.ManyToManyField):
            return {'widget': website.views.widgets.AdminCheckboxSelect(
                attrs={'inline': style == 'checkbox-inline'}),
                'help_text': None}
        if type(style) == dict: return style

    @pluginhook
    def get_model_form(self, **kwargs):

        exclude = self.exclude
        exclude.extend(self.get_readonly_fields())
        if self.exclude is None and hasattr(self.form, '_meta') and self.form._meta.exclude:
            # 如果 :attr:`~website.view.website.ModelViewTemplate.exclude` 是 None，并且 form 的 Meta.exclude 不为空，
            # 则使用 form 的 Meta.exclude
            exclude.extend(self.form._meta.exclude)
        defaults = {
            "form": self.form,
            "fields": self.fields or None,
            "exclude": exclude,
            "formfield_callback": self.formfield_for_dbfield,  # 设置生成表单字段的回调函数
        }
        defaults.update(kwargs)
        return modelform_factory(self.model, **defaults)

    # post@1
    @pluginhook
    def prepare_form(self):
        self.model_form = self.get_model_form()

    # post@2
    # get@1
    @pluginhook
    def instance_forms(self):
        self.form_obj = self.model_form(**self.get_form_datas())

    # post@3
    # get@2
    def setup_forms(self):
        helper = self.get_form_helper()
        if helper:
            self.form_obj.helper = helper

    # post@4
    @pluginhook
    def valid_forms(self):
        """
        验证 Form 的数据合法性
        """
        return self.form_obj.is_valid()

    @pluginhook
    def get_form_layout(self):
        """
        返回 Form Layout ，如果您设置了 :attr:`form_layout` 属性，则使用该属性，否则该方法会自动生成 Form Layout 。
        有关 Form Layout 的更多信息可以参看 `Crispy Form 文档 <http://django-crispy-forms.readthedocs.org/en/latest/layouts.html>`_
        设置 Form Layout 可以非常灵活的显示表单页面的各个元素
        """
        layout = copy.deepcopy(self.form_layout)
        fields_keys = [i for i in self.form_obj.fields.keys()]
        fields = fields_keys + [i for i in self.get_readonly_fields()]

        if layout is None:
            layout = Layout(Container(Col('full',
                                          Fieldset("", *fields, css_class="unsort no_title"), horizontal=True, span=12)
                                      ))
        elif type(layout) in (list, tuple) and len(layout) > 0:
            # 如果设置的 layout 是一个列表，那么按以下方法生成
            if isinstance(layout[0], Column):
                fs = layout
            elif isinstance(layout[0], (Fieldset, TabHolder)):
                fs = (Col('full', *layout, horizontal=True, span=12),)
            else:
                fs = (Col('full', Fieldset("", *layout, css_class="unsort no_title"), horizontal=True, span=12),)

            layout = Layout(Container(*fs))

            rendered_fields = [i[1] for i in layout.get_field_names()]
            container = layout[0].fields
            other_fieldset = Fieldset(_('Other Fields'), *[f for f in fields if f not in rendered_fields])

            # 将所有没有显示的字段和在一个 Fieldset 里面显示
            if len(other_fieldset.fields) and not self.hide_other_field:
                if len(container) and isinstance(container[0], Column):
                    # 把其他字段放在第一列显示
                    container[0].fields.append(other_fieldset)
                else:
                    container.append(other_fieldset)

        return layout

    @pluginhook
    def get_form_helper(self):

        """
        取得 Crispy Form 需要的 FormHelper。具体信息可以参看 `Crispy Form 文档 <http://django-crispy-forms.readthedocs.org/en/latest/tags.html#crispy-tag>`_
        """
        helper = FormHelper()
        helper.form_tag = False  # 默认不需要 crispy 生成 form_tag
        helper.include_media = False
        helper.add_layout(self.get_form_layout())

        # 处理只读字段
        readonly_fields = self.get_readonly_fields()
        if readonly_fields:
            # 使用 :class:`website.view.detail.DetailViewMixin` 来显示只读字段的内容
            detail = self.getmodelviewclass(
                DetailViewMixin, self.model, self.form_obj.instance)
            for field in readonly_fields:
                # 替换只读字段
                helper[field].wrap(ReadOnlyField, detail=detail)

        return helper

    @pluginhook
    def get_readonly_fields(self):
        """
        返回只读字段，子类或 iview 可以复写该方法
        """
        return self.readonly_fields

    @pluginhook
    def save_forms(self):
        self.new_obj = self.form_obj.save(commit=False)

    @pluginhook
    def save_related(self):
        self.form_obj.save_m2m()

    @pluginhook
    def save_models(self):
        self.new_obj.save()

    @csrf_protect_m
    @pluginhook
    def get(self, request, *args, **kwargs):
        self.instance_forms()  # -> self.form_obj
        self.setup_forms()

        return self.get_response()

    @csrf_protect_m
    @dutils.commit_on_success
    @pluginhook
    def post(self, request, *args, **kwargs):
        self.instance_forms()
        self.setup_forms()

        if self.valid_forms():
            self.save_forms()

            ret = self.save_models()
            if isinstance(ret, str):
                self.message_user(ret, 'error')
                return self.get_response()
            if isinstance(ret, HttpResponse):
                return ret

            self.save_related()
            self.after_save()
            response = self.post_response()
            if isinstance(response, str):
                return HttpResponseRedirect(response)
            else:
                return response

        return self.get_response()

    def after_save(self):
        pass

    @pluginhook
    def get_context(self):
        add = self.org_obj is None
        change = self.org_obj is not None

        new_context = {
            'form': self.form_obj,
            'original': self.org_obj,
            'show_delete': self.org_obj is not None,
            'add': add,
            'change': change,
            'errors': self.get_error_list(),

            'has_add_permission': self.has_add_permission(),
            'has_view_permission': self.has_view_permission(),
            'has_change_permission': self.has_change_permission(self.org_obj),
            'has_delete_permission': self.has_delete_permission(self.org_obj),

            'has_file_field': True,  # FIXME - this should check if form or formsets have a FileField,
            'has_absolute_url': hasattr(self.model, 'get_absolute_url'),
            'form_url': '',
            'content_type_id': ContentType.objects.get_for_model(self.model).id,
            'save_as': self.save_as,
            'save_on_top': self.save_on_top,
        }

        # for submit line
        new_context.update({
            'onclick_attrib': '',
            'show_delete_link': (new_context['has_delete_permission']
                                 and (change or new_context['show_delete'])),
            'show_save_as_new': change and self.save_as,
            'show_save_and_add_another': new_context['has_add_permission'] and
                                         (not self.save_as or add),
            'show_save_and_continue': new_context['has_change_permission'],
            'show_save': True
        })

        if self.org_obj and new_context['show_delete_link']:
            new_context['delete_url'] = self.model_admin_url(
                'delete', self.org_obj.pk)

        context = super(ModelFormViewTemplate, self).get_context()
        context.update(new_context)
        return context

    @pluginhook
    def get_error_list(self):
        """
        获取表单的错误信息列表。
        """
        errors = dutils.ErrorList()
        if self.form_obj.is_bound:
            errors.extend([i for i in self.form_obj.errors.values()])
        return errors

    @pluginhook
    def get_media(self):
        return super(ModelFormViewTemplate, self).get_media() + self.form_obj.media + \
               self.vendor('website.page.form.js', 'website.form.css')


class ListCell:

    def __init__(self, field_name, row):
        self.classes = []
        self.text = '&nbsp;'
        self.wraps = []
        self.tag = 'td'
        self.tag_attrs = []
        self.allow_tags = False
        self.btns = []
        self.menus = []
        self.is_display_link = False
        self.row = row
        self.field_name = field_name
        self.field = None
        self.attr = None
        self.value = None

    @property
    def label(self):
        text = mark_safe(
            self.text) if self.allow_tags else conditional_escape(self.text)
        if force_str(text) == '':
            text = mark_safe('&nbsp;')
        for wrap in self.wraps:
            text = mark_safe(wrap % text)
        return text

    @property
    def tagattrs(self):
        return mark_safe(
            '%s%s' % ((self.tag_attrs and ' '.join(self.tag_attrs) or ''),
                      (self.classes and (' class="%s"' % ' '.join(self.classes)) or '')))


class HeaderCell(ListCell):
    """
    表头单元格
    """

    def __init__(self, field_name, row):
        super(HeaderCell, self).__init__(field_name, row)
        self.tag = 'th'
        self.tag_attrs = ['scope="col"']
        self.sortable = False
        self.allow_tags = True
        self.sorted = False
        self.ascending = None
        self.sort_priority = None
        self.url_primary = None
        self.url_remove = None
        self.url_toggle = None


class ListRow(dict):

    def __init__(self):
        self.cells = []

    def add_cell(self, name, text):
        cell = ListCell(name, self)
        cell.text = text
        self.cells.append(cell)


def inclusion_tag(file_name, context_class=Context, takes_context=False):
    """
    为 ViewTemplate 的 block appended_views 提供的便利方法，作用等同于 :meth:`django.template.Library.inclusion_tag`
    """

    def wrap(func):
        @functools.wraps(func)
        def method(self, context, nodes, *arg, **kwargs):
            _dict = func(self, context, nodes, *arg, **kwargs)
            from django.template.loader import get_template, select_template
            if isinstance(file_name, Template):
                t = file_name
            elif not isinstance(file_name, str) and is_iterable(file_name):
                t = select_template(file_name)
            else:
                t = get_template(file_name)
            _dict['autoescape'] = context.autoescape
            _dict['use_l10n'] = context.use_l10n
            _dict['use_tz'] = context.use_tz
            # 添加 view
            _dict['cl'] = context['cl']
            csrf_token = context.get('csrf_token', None)
            if csrf_token is not None:
                _dict['csrf_token'] = csrf_token
            nodes.append(t.render(_dict))

        return method

    return wrap


class ListViewTemplate(ModelViewTemplate):
    paginator_class = Paginator
    can_show_all = True
    select_close = True
    grid = True

    # request@0
    def init_request(self, *args, **kwargs):
        """
        初始化请求, 首先判断当前用户有无 view 权限, 而后进行一些生成数据列表所需的变量的初始化操作.
        """
        # print('@init_request')
        if not self.has_view_permission():
            raise PermissionDenied

        request = self.request
        # request.session['LIST_QUERY'] = (self.model_info, self.request.META['QUERY_STRING'])
        if 'pop' in self.request.GET:
            self.pop = True
            # self.base_template = 'website/base.bootstrap_content.tpl'

        self.list_display = self.get_list_display()  # 插件在其后起作用
        self.list_display_links = self.get_list_display_links()

        # 获取当前页码
        try:
            self.page_num = int(request.GET.get(PAGE_VAR, 0))
        except ValueError:
            self.page_num = 0

        # 获取各种参数
        self.show_all = ALL_VAR in request.GET
        self.to_field = request.GET.get('t')
        self.params = dict(request.GET.items())
        # 删除已经获取的参数, 因为后面可能要用 params 或过滤数据
        if 'p' in self.params:
            del self.params['p']
        if 'e' in self.params:
            del self.params['e']

    # get@0
    @csrf_protect_m
    @pluginhook
    def get(self, request, *args, **kwargs):
        response = self.get_result_list()
        if response:
            return response

        context = self.get_context()
        context.update(kwargs or {})

        response = self.get_response(context, *args, **kwargs)
        context.update({'current_app': self.website.module_name})
        return response or TemplateResponse(request, self.list_template or self.get_template_list('views/grid.tpl'),
                                            context)

    # get@1
    @pluginhook
    def get_result_list(self):
        return self.make_result_list()

    # get@11
    def make_result_list(self):
        """
        生成列表页结果数据
        result_list
        """
        # 排序及过滤等处理后的 queryset
        self.list_queryset = self.get_list_queryset()
        self.ordering_field_columns = self.get_ordering_field_columns()
        self.paginator = self.get_paginator()

        # 获取当前据数目
        self.result_count = self.paginator.count
        if self.can_show_all:
            self.can_show_all = self.result_count <= self.list_max_show_all
        self.multi_page = self.result_count > self.list_per_page

        if (self.show_all and self.can_show_all) or not self.multi_page:
            self.result_list = self.list_queryset._clone()
        else:
            try:
                self.result_list = self.paginator.page(
                    self.page_num + 1).object_list
            except InvalidPage:
                # 分页错误, 这里的错误页面需要调整一下
                if configs.ERROR_FLAG in list(self.request.GET.keys()):
                    return SimpleTemplateResponse('website/views/invalid_setup.tpl', {
                        'title': _('Database error'),
                    })
                return HttpResponseRedirect(
                    self.request.path + '?' + configs.ERROR_FLAG + '=1')
        self.has_more = self.result_count > (
                self.list_per_page * self.page_num + len(self.result_list))

    # get@111
    @pluginhook
    def get_list_queryset(self):

        # 首先取得基本的 queryset
        if self.search_sphinx_ins:
            query = self.request.GET.get('_q_', '')
            if query:
                query_set = self.search_sphinx_ins.query(query)
                query_set.set_options(mode='SPH_MATCH_EXTENDED2')
                query_set.set_options(rankmode='SPH_SORT_RELEVANCE')
                query_set.order_by('-@weight', '-@id')
                query_set._maxmatches = 500
                query_set._limit = 500

                sph_results = query_set._get_sphinx_results()
                result_ids = [r['id'] for r in sph_results['matches'][:500]]
                if query.isdigit():
                    result_ids.append(int(query))
                queryset = self.queryset().filter(id__in=result_ids)
            else:
                queryset = self.queryset()
        else:
            queryset = self.queryset()
        if not queryset.query.select_related:
            if self.list_select_related:
                queryset = queryset.select_related()
            elif not self.list_select_related:
                related_fields = []
                for field_name in self.list_display:
                    try:
                        field = self.opts.get_field(field_name)
                    except models.FieldDoesNotExist:
                        pass
                    else:
                        if isinstance(field.remote_field, models.ManyToOneRel):
                            related_fields.append(field_name)
                if related_fields:
                    queryset = queryset.select_related(*related_fields)
            else:
                pass

        queryset = queryset.order_by(*self.get_ordering())
        return queryset

    # get@2
    @pluginhook
    def get_context(self):
        if hasattr(self, 'verbose_name'):
            self.opts.verbose_name = self.verbose_name
            self.opts.verbose_name_plural = self.verbose_name
        self.title = _('%s') % (getattr(self, 'title', False) or self.opts.verbose_name)

        # 获取所有可供显示的列的信息
        model_fields = [(f, f.name in self.list_display, self.get_check_field_url(f))
                        for f in (list(self.opts.fields) + self.get_model_method_fields()) if
                        f.name not in self.list_exclude]
        new_context = {
            'model_name': self.opts.verbose_name_plural,
            'title': self.title,
            'cl': self,
            'model_fields': self.get_model_fields(),
            'clean_select_field_url': self.get_query_string(remove=[COL_LIST_VAR]),
            'has_add_permission': self.has_add_permission(),
            'app_label': self.app_label,
            'brand_name': self.opts.verbose_name_plural,
            'brand_icon': self.get_menu_icon(self.model),
            'add_url': self.model_admin_url('add'),
            'result_headers': self.makeheaders(),
            'results': self.results(),
            'nav_buttons': mark_safe(' '.join(self.get_nav_btns())),
        }
        self.get_query_string(remove=[COL_LIST_VAR]).replace('/', '-')

        if self.list_tabs:
            cur_tab = self.request.GET.get('_tab', '0')
            new_context['cur_tab'] = int(cur_tab)
        context = super(ListViewTemplate, self).get_context()
        context.update(new_context)
        if self.pop:
            if self.website.style_adminlte:
                context['base_template'] = 'website/model_admin_urlcontent.tpl'
            else:
                context['base_template'] = 'website/base.bootstrap_content.tpl'
        return context

    @pluginhook
    def post_result_list(self):
        return self.make_result_list()

    def _get_default_ordering(self):
        ordering = []
        if self.ordering:
            ordering = self.ordering
        elif self.opts:
            if self.opts.ordering:
                ordering = self.opts.ordering
        return ordering

    @pluginhook
    def get_response(self, context, *args, **kwargs):
        pass

    @pluginhook
    def post_response(self, *args, **kwargs):
        """
        列表的 POST 请求, 该方法默认无返回内容, 插件可以复写该方法, 返回指定的 HttpResponse.
        """
        pass

    @pluginhook
    def get_ordering_field_columns(self):
        """
        从请求参数中得到排序信息 eg o=-create_time.status.-intro.title
        """
        ordering = self._get_default_ordering()
        ordering_fields = SortedDict()
        if configs.ORDER_VAR not in self.params or not self.params[
            configs.ORDER_VAR]:
            for field in ordering:
                if field.startswith('-'):
                    field = field[1:]
                    order_type = 'desc'
                else:
                    order_type = 'asc'
                for attr in self.list_display:
                    if self.get_ordering_field(attr) == field:
                        ordering_fields[field] = order_type
                        break
        else:
            for p in self.params[configs.ORDER_VAR].split('.'):
                __, pfx, field_name = p.rpartition('-')
                ordering_fields[field_name] = 'desc' if pfx == '-' else 'asc'
        return ordering_fields

    @pluginhook
    def get_paginator(self):
        """
        返回 paginator 实例
        """
        return self.paginator_class(self.list_queryset, self.list_per_page, 0, True)

    @pluginhook
    def get_page_number(self, i):
        """
        返回翻页组件各页码显示的 HTML 内容. 默认使用 bootstrap 样式

        :param i: 页码, 可能是 ``DOT``
        """
        if i == DOT:
            return mark_safe('<span class="dot-page">...</span> ')
        elif i == self.page_num:
            return mark_safe('<span class="this-page">%d</span> ' % (i + 1))
        else:
            return mark_safe('<a href="%s"%s>%d</a> ' % (escape(self.get_query_string({
                configs.PAGE_VAR: i})),
                                                         (i == self.paginator.num_pages - 1 and ' class="end"' or ''),
                                                         i + 1))

    @pluginhook
    def get_media(self):
        """
        返回列表页面的 Media, 该页面添加了 ``website.page.list.js`` 文件
        """
        media = super().get_media() + self.vendor('website.page.list.js', 'website.page.form.js',
                                                  'website.form.css')
        if self.list_display_links_details:
            media += self.vendor('website.plugin.details.js')
        return media

    def get_model_fields(self):
        return []

    def get_nav_btns(self):
        return []

    @pluginhook
    def get_list_display(self):
        """
        list_display 列表显示列
        base_list_display    原始的显示列 导出使用
        """
        self.base_list_display = (COL_LIST_VAR in self.request.GET and self.request.GET[COL_LIST_VAR] != "" and \
                                  self.request.GET[COL_LIST_VAR].split('.')) or self.list_display
        return list(self.base_list_display)

    @pluginhook
    def get_list_display_links(self):
        """
        用于显示链接的字段    修改链接/查看链接
        list_display_links
        """
        if self.list_display_links or not self.list_display:
            return self.list_display_links
        else:
            return list(self.list_display)[:1]

    @inclusion_tag('website/includes/pagination.tpl')
    def block_pagination(self, context, nodes, page_type='normal'):
        paginator, page_num = self.paginator, self.page_num

        pagination_required = (
                                      not self.show_all or not self.can_show_all) and self.multi_page
        if not pagination_required:
            page_range = []
        else:
            ON_EACH_SIDE = {'normal': 5, 'small': 3}.get(page_type, 3)
            ON_ENDS = 2

            # 10页以内显示每页的链接
            if paginator.num_pages <= 10:
                page_range = range(paginator.num_pages)
            else:
                page_range = []
                if page_num > (ON_EACH_SIDE + ON_ENDS):
                    page_range.extend(range(0, ON_EACH_SIDE - 1))
                    page_range.append(DOT)
                    page_range.extend(
                        range(page_num - ON_EACH_SIDE, page_num + 1))
                else:
                    page_range.extend(range(0, page_num + 1))
                if page_num < (paginator.num_pages - ON_EACH_SIDE - ON_ENDS - 1):
                    page_range.extend(
                        range(page_num + 1, page_num + ON_EACH_SIDE + 1))
                    page_range.append(DOT)
                    page_range.extend(range(
                        paginator.num_pages - ON_ENDS, paginator.num_pages))
                else:
                    page_range.extend(range(page_num + 1, paginator.num_pages))

        need_show_all_link = self.can_show_all and not self.show_all and self.multi_page
        return {
            'cl': self,
            'pagination_required': pagination_required,
            'show_all_url': need_show_all_link and self.get_query_string({ALL_VAR: ''}),
            'page_range': map(self.get_page_number, page_range),
            'ALL_VAR': ALL_VAR,
            '1': 1,
        }

    @pluginhook
    def get_ordering_field(self, field_name):
        """
        验证排序字段 field_name 的有效性
        """
        try:
            field = self.opts.get_field(field_name)
            return field.name
        except models.FieldDoesNotExist:
            # 在非 db field 中获取
            if callable(field_name):
                attr = field_name
            elif hasattr(self, field_name):
                attr = getattr(self, field_name)
            else:
                attr = getattr(self.model, field_name)
            return getattr(attr, 'admin_order_field', None)

    @pluginhook
    def get_ordering(self):
        ordering = list(super(ListViewTemplate, self).get_ordering() or self._get_default_ordering())
        if ORDER_VAR in self.params and self.params[ORDER_VAR]:
            # Clear ordering and used params
            order_list = [p.rpartition('-') for p in self.params[ORDER_VAR].split('.')]
            ordering = []
            for __, pfx, field_name in order_list:
                check_name = self.get_ordering_field(field_name)
                if check_name:
                    ordering.append(pfx + check_name)

        pk_name = self.opts.pk.name
        if not (set(ordering) & set(['pk', '-pk', pk_name, '-' + pk_name])):
            ordering.append('-pk')
        return ordering

    def get_check_field_url(self, f):
        """
        返回 ``显示列`` 菜单项中每一项的 url.
        """
        # 使用 :attr:`base_list_display` 作为基础列, 因为 :attr:`list_display` 可能已经被插件修改
        fields = [fd for fd in self.base_list_display if fd != f.name]
        if len(self.base_list_display) == len(fields):
            if f.primary_key:
                fields.insert(0, f.name)
            else:
                fields.append(f.name)
        return self.get_query_string({COL_LIST_VAR: '.'.join(fields)})

    def get_model_method_fields(self):
        """
        获得模型的方法型字段 （目前主要用在显示列的控制）
        is_column、verbose_name
        """
        methods = []
        for name in dir(self):
            try:
                if getattr(getattr(self, name), 'is_column', False):
                    methods.append((name, getattr(self, name)))
            except:
                pass
        return [FakeMethodField(name, getattr(method, 'verbose_name', capfirst(name.replace('_', ' '))))
                for name, method in methods]

    def get_model_fields(self):
        '''
        获取所有可供显示的列的信息
        '''
        model_fields = [(f, f.name in self.list_display, self.get_check_field_url(f))
                        for f in (list(self.opts.fields) + self.get_model_method_fields()) if
                        f.name not in self.list_exclude]
        return model_fields

    @csrf_protect_m
    @pluginhook
    def post(self, request, *args, **kwargs):
        return self.post_result_list() or self.post_response(*args, **kwargs) or self.get(request, *args, **kwargs)

    def get_detail_url(self, obj):
        return self.model_admin_url("detail", getattr(obj, self.pk_name))

    @pluginhook
    def makeheader(self, field_name, row):
        ordering_field_columns = self.ordering_field_columns
        item = HeaderCell(field_name, row)
        text, attr = label_for_field(field_name, self.model,
                                     model_admin=self,
                                     return_attr=True
                                     )
        item.text = text
        item.attr = attr
        if attr and not getattr(attr, "admin_order_field", None):
            return item

        # 接下来就是处理列排序的问题了
        th_classes = ['sortable']
        order_type = ''
        new_order_type = 'desc'
        sort_priority = 0
        sorted = False
        # 判断当前列是否已经排序
        if field_name in ordering_field_columns:
            sorted = True
            order_type = ordering_field_columns.get(field_name).lower()
            sort_priority = list(ordering_field_columns.keys()).index(field_name) + 1
            th_classes.append('sorted %sending' % order_type)
            new_order_type = {'asc': 'desc', 'desc': 'asc'}[order_type]

        # build new ordering param
        o_list_asc = []  # URL for making this field the primary sort
        o_list_desc = []  # URL for making this field the primary sort
        o_list_remove = []  # URL for removing this field from sort
        o_list_toggle = []  # URL for toggling order type for this field
        make_qs_param = lambda t, n: ('-' if t == 'desc' else '') + str(n)

        for j, ot in list(ordering_field_columns.items()):
            if j == field_name:  # Same column
                param = make_qs_param(new_order_type, j)
                # We want clicking on this header to bring the ordering to the
                # front
                o_list_asc.insert(0, j)
                o_list_desc.insert(0, '-' + j)
                o_list_toggle.append(param)
                # o_list_remove - omit
            else:
                param = make_qs_param(ot, j)
                o_list_asc.append(param)
                o_list_desc.append(param)
                o_list_toggle.append(param)
                o_list_remove.append(param)

        if field_name not in ordering_field_columns:
            o_list_asc.insert(0, field_name)
            o_list_desc.insert(0, '-' + field_name)

        item.sorted = sorted
        item.sortable = True
        item.ascending = (order_type == "asc")
        item.sort_priority = sort_priority

        # 列排序菜单的内容
        menus = [
            ('asc', o_list_asc, 'caret-up', _('Sort ASC')),
            ('desc', o_list_desc, 'caret-down', _('Sort DESC')),
        ]
        if sorted:
            row['num_sorted_fields'] = row['num_sorted_fields'] + 1
            menus.append((None, o_list_remove, 'times', _('Cancel Sort')))
            item.btns.append('<a class="toggle" href="%s"><i class="fa fa-%s"></i></a>' % (
                self.get_query_string({ORDER_VAR: '.'.join(o_list_toggle)}),
                'sort-up' if order_type == "asc" else 'sort-down'))

        item.menus.extend(['<li%s><a href="%s" class="active"><i class="fa fa-%s"></i> %s</a></li>' %
                           (
                               (' class="active"' if sorted and order_type == i[
                                   0] else ''),
                               self.get_query_string({ORDER_VAR: '.'.join(i[1])}), i[2], i[3]) for i in menus])
        item.classes.extend(th_classes)

        return item

    @pluginhook
    def makeheaders(self):
        row = ListRow()
        row['num_sorted_fields'] = 0
        row.cells = [self.makeheader(field_name, row) for field_name in self.list_display]
        return row

    @pluginhook
    def makecell(self, obj, field_name, row):
        item = ListCell(field_name, row)  # 首先初始化
        field_name_split = field_name.split('.')
        field_name = field_name_split[0]
        try:
            f, attr, value = lookup_field(field_name, obj, self)
        except (AttributeError, ObjectDoesNotExist):
            item.text = mark_safe("<span class='text-muted'>%s</span>" % EMPTY_CHANGELIST_VALUE)
        else:
            if f is None:
                # Model 属性或是 iview 属性列
                item.allow_tags = getattr(attr, 'allow_tags', False)
                boolean = getattr(attr, 'boolean', False)
                if boolean:
                    item.allow_tags = True
                    item.text = boolean_icon(value)
                else:
                    item.text = smart_str(value)
            else:
                # 处理关联列

                if isinstance(f, models.ManyToOneRel):
                    field_val = getattr(obj, f.name)
                    if field_val is None:
                        item.text = mark_safe("<span class='text-muted'>%s</span>" % EMPTY_CHANGELIST_VALUE)
                    else:
                        if len(field_name_split) > 1:
                            item.text = getattr(field_val, field_name_split[1])
                        else:
                            item.text = field_val
                else:
                    item.text = display_for_field(value, f)
                if isinstance(f, models.DateField) \
                        or isinstance(f, models.TimeField) \
                        or isinstance(f, models.ForeignKey):
                    item.classes.append('nowrap')

            item.field = f
            item.attr = attr
            item.value = value
        if not hasattr(obj, '_nolink'):
            # 如果没有指定 ``list_display_links`` , 使用第一列作为内容连接列.
            if (item.row['is_display_first'] and not self.list_display_links) \
                    or field_name in self.list_display_links:
                item.row['is_display_first'] = False
                item.is_display_link = True
                if self.list_display_links_details:
                    url = self.get_detail_url(obj)
                else:
                    url = self.get_object_url(obj)
                if self.pop:
                    if 's' in self.request.GET:
                        show = getattr(obj, self.request.GET.get('s'))
                        if callable(show): show = show()
                    else:
                        show = escape(Truncator(obj).words(14, truncate='...'))
                    show = str(show).replace('%', '%%').replace("\'", "\\\'")
                    pop = format_html(' class="for_multi_select" show="{0}" sid="{1}" ', show,
                                      getattr(obj, str(self.request.GET.get('t')), ''))
                else:
                    pop = ''
                item.wraps.append('<a href="%s" %s>%%s</a>' % (url, pop))

        return item

    @pluginhook
    def makerow(self, obj):
        row = ListRow()
        row['is_display_first'] = True
        row['object'] = obj
        row.cells = [self.makecell(
            obj, field_name, row) for field_name in self.list_display]
        return row

    @pluginhook
    def results(self):
        results = []
        for obj in self.result_list:
            results.append(self.makerow(obj))
        return results


class TableViewTemplate(ListViewTemplate):
    pass


class CreateViewTemplate(ModelFormViewTemplate):

    def init_request(self, *args, **kwargs):
        self.org_obj = None

        if not self.has_add_permission():
            raise PermissionDenied

        # comm method for both get and post
        self.prepare_form()

    @pluginhook
    def get_form_datas(self):
        """
        从 Request 中返回 Form 的初始化数据
        """
        if self.request_method == 'get':
            initial = dict(list(self.request.GET.items()))
            for k in initial:
                try:
                    f = self.opts.get_field(k)
                except models.FieldDoesNotExist:
                    continue
                if isinstance(f, models.ManyToManyField):
                    # 如果是多对多的字段，则使用逗号分割
                    initial[k] = initial[k].split(",")
            return {'initial': initial}
        else:
            return {'data': self.request.POST, 'files': self.request.FILES}

    @pluginhook
    def get_context(self):
        """
        **Context Params**:

            ``title`` : 表单标题
        """
        new_context = {
            'title': _('Add %s') % force_str(self.opts.verbose_name),
        }
        context = super(CreateViewTemplate, self).get_context()
        context.update(new_context)
        return context

    @pluginhook
    def get_breadcrumb(self):
        bcs = super(ModelFormViewTemplate, self).get_breadcrumb()
        item = {'title': _('Add %s') % force_str(self.opts.verbose_name)}
        if self.has_add_permission():
            item['url'] = self.model_admin_url('add')
        bcs.append(item)
        return bcs

    @pluginhook
    def get_response(self):
        """
        返回显示表单页面的 Response ，子类或是 iview 可以复写该方法
        """
        context = self.get_context()
        context.update(self.kwargs or {})

        return TemplateResponse(
            self.request, self.add_form_template or self.get_template_list(
                'views/model_form.tpl'),
            context)

    @pluginhook
    def post_response(self):
        """
        当成功保存数据后，会调用该方法返回 HttpResponse 或跳转地址
        """
        request = self.request

        msg = _(
            'The %(name)s "%(obj)s" was added successfully.') % {'name': force_str(self.opts.verbose_name),
                                                                 'obj': force_str(self.new_obj)}

        param_list = self.param_list()
        if "_continue" in param_list:
            self.message_user(
                msg + ' ' + _("You may edit it again below."), 'success')
            # 继续编辑
            return self.model_admin_url('change', self.new_obj._get_pk_val())

        if "_addanother" in param_list:
            self.message_user(msg + ' ' + (_("You may add another %s below.") % force_str(self.opts.verbose_name)),
                              'success')
            # 返回添加页面添加另外一个
            return request.path
        else:
            self.message_user(msg, 'success')

            # 如果没有查看列表的权限就跳转到主页
            if "_redirect" in param_list:
                return self.get_param('_redirect')
            elif self.has_view_permission():
                if self.add_redirect_url:
                    return self.add_redirect_url % self.new_obj._get_pk_val()
                else:
                    return self.model_admin_url('changelist')
            else:
                return self.get_site_url('index')

    def log_addition(self, request, object):
        """
        添加对象日志
        """
        from django.contrib.baseadmin.models import LogEntry, ADDITION
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(object).pk,
            object_id=object.pk,
            object_repr=force_text(object),
            action_flag=ADDITION
        )

    def do_add(self):
        self.new_obj.save()
        if self.log:
            self.log_addition(self.request, self.new_obj)

    @pluginhook
    def save_models(self):
        return self.do_add()


class UpdateViewTemplate(ModelFormViewTemplate):
    result_count = 1
    result_list = []

    def init_request(self, object_id, *args, **kwargs):
        self.org_obj = self.get_object(unquote(object_id))

        if not self.has_change_permission(self.org_obj):
            raise PermissionDenied

        if self.org_obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') %
                          {'name': force_str(self.opts.verbose_name), 'key': escape(object_id)})

        # comm method for both get and post
        self.prepare_form()

    @pluginhook
    def get_form_datas(self):
        """
        获取 Form 数据
        """
        params = {'instance': self.org_obj}
        if self.request_method == 'post':
            params.update(
                {'data': self.request.POST, 'files': self.request.FILES})
        return params

    @pluginhook
    def get_context(self):
        """
        **Context Params**:

            ``title`` : 表单标题

            ``object_id`` : 修改的数据对象的 id
        """
        new_context = {
            'title': _('Change %s') % force_str(self.org_obj),
            'object_id': str(self.org_obj.pk),
            'cl': self
        }
        context = super(UpdateViewTemplate, self).get_context()
        context.update(new_context)
        return context

    @pluginhook
    def get_breadcrumb(self):
        bcs = super(ModelFormViewTemplate, self).get_breadcrumb()

        item = {'title': force_str(self.org_obj)}
        if self.has_change_permission():
            item['url'] = self.model_admin_url('change', self.org_obj.pk)
        bcs.append(item)

        return bcs

    @pluginhook
    def get_response(self, *args, **kwargs):
        context = self.get_context()
        context.update(kwargs or {})

        return TemplateResponse(
            self.request, self.change_form_template or self.get_template_list(
                'views/model_form.tpl'),
            context)

    def post(self, request, *args, **kwargs):
        if "_saveasnew" in self.param_list():
            return self.getmodelviewclass(CreateViewTemplate, self.model).post(request)
        return super(UpdateViewTemplate, self).post(request, *args, **kwargs)

    @pluginhook
    def post_response(self):
        """
        当成功修改数据后，会调用该方法返回 HttpResponse 或跳转地址
        """
        opts = self.new_obj._meta
        obj = self.new_obj
        request = self.request
        verbose_name = opts.verbose_name

        pk_value = obj._get_pk_val()

        msg = _('The %(name)s "%(obj)s" was changed successfully.') % {'name':
                                                                           force_str(verbose_name),
                                                                       'obj': force_str(obj)}
        param_list = self.param_list()
        if "_continue" in param_list:
            self.message_user(
                msg + ' ' + _("You may edit it again below."), 'success')
            # 返回原页面继续编辑
            return request.path
        elif "_addanother" in param_list:
            self.message_user(msg + ' ' + (_("You may add another %s below.")
                                           % force_str(verbose_name)), 'success')
            return self.model_admin_url('add')
        else:
            self.message_user(msg, 'success')
            # 如果没有查看列表的权限就跳转到主页
            if "_redirect" in param_list:
                return self.get_param('_redirect')
            elif self.has_view_permission():
                change_list_url = self.model_admin_url('changelist')
                return change_list_url
            else:
                return self.get_site_url('index')

    def get_org(self):
        return self.get_object(unquote(self.org_obj.pk))

    def do_update(self):
        '''
        self.org_obj = self.get_org()
        self.new_obj
        '''
        self.new_obj.save()
        if self.log:
            change_message = self.construct_change_message(self.request, self.form_obj, getattr(self, 'formsets', []))
            self.log_change(self.request, self.new_obj, change_message)

    @pluginhook
    def save_models(self):
        """
        保存数据到数据库中
        """
        return self.do_update()

    def log_change(self, request, object, message):
        """
        更新对象日志
        """
        from django.contrib.baseadmin.models import LogEntry, CHANGE
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(object).pk,
            object_id=object.pk,
            object_repr=force_text(object),
            action_flag=CHANGE,
            change_message=message
        )

    def construct_change_message(self, request, form, formsets):
        """
        Construct a change message from a changed object.
        """
        from django.utils.encoding import force_text
        from django.utils.text import get_text_list

        change_message = []
        if form.changed_data:
            change_message.append(_('Changed %s.') % get_text_list(form.changed_data, _('and')))

        if formsets:
            for formset in formsets:
                for added_object in formset.new_objects:
                    change_message.append(_('Added %(name)s "%(object)s".')
                                          % {'name': force_text(added_object._meta.verbose_name),
                                             'object': force_text(added_object)})
                for changed_object, changed_fields in formset.changed_objects:
                    change_message.append(_('Changed %(list)s for %(name)s "%(object)s".')
                                          % {'list': get_text_list(changed_fields, _('and')),
                                             'name': force_text(changed_object._meta.verbose_name),
                                             'object': force_text(changed_object)})
                for deleted_object in formset.deleted_objects:
                    change_message.append(_('Deleted %(name)s "%(object)s".')
                                          % {'name': force_text(deleted_object._meta.verbose_name),
                                             'object': force_text(deleted_object)})
        change_message = ' '.join(change_message)
        return change_message or _('No fields changed.')


class DetailView(ModelViewTemplate):
    form = forms.ModelForm
    detail_layout = None
    detail_show_all = True
    detail_template = None

    def init_request(self, object_id, *args, **kwargs):
        """
        初始化操作。根据传入的 ``object_id`` 取得要被显示的数据对象，而后进行权限判断, 如果没有数据查看权限会显示禁止页面.
        """
        self.obj = self.get_object(unquote(object_id))

        # 须有查看权限
        if not self.has_view_permission(self.obj):
            raise PermissionDenied

        if self.obj is None:
            raise Http404(
                _('%(name)s object with primary key %(key)r does not exist.') %
                {'name': force_str(self.opts.verbose_name), 'key': escape(object_id)})
        self.org_obj = self.obj

    @pluginhook
    def get_form_layout(self):
        """
        返回 Form Layout ，如果您设置了 :attr:`detail_layout` 属性，则使用 :attr:`form_layout` 属性，如果都没有该方法会自动生成 Form Layout 。
        有关 Form Layout 的更多信息可以参看 `Crispy Form 文档 <http://django-crispy-forms.readthedocs.org/en/latest/layouts.html>`_
        设置 Form Layout 可以非常灵活的显示页面的各个元素
        """
        # 复制避免修改属性值
        layout = copy.deepcopy(self.detail_layout or self.form_layout)

        if layout is None:
            fields = list(self.form_obj.fields.keys()) + list(self.get_readonly_fields())
            layout = Layout(Container(Col('full',
                                          Fieldset(
                                              "", *fields,
                                              css_class="unsort no_title"), horizontal=True, span=12)
                                      ))
        elif type(layout) in (list, tuple) and len(layout) > 0:
            # 如果设置的 layout 是一个列表，那么按以下方法生成
            if isinstance(layout[0], Column):
                fs = layout
            elif isinstance(layout[0], (Fieldset, TabHolder)):
                fs = (Col('full', *layout, horizontal=True, span=12),)
            else:
                fs = (
                    Col('full', Fieldset("", *layout, css_class="unsort no_title"), horizontal=True, span=12),)

            layout = Layout(Container(*fs))

            if self.detail_show_all:
                # 显示没有在 Layout 中出现的字段
                rendered_fields = [i[1] for i in layout.get_field_names()]
                container = layout[0].fields
                other_fieldset = Fieldset(_('Other Fields'), *[
                    f for f in list(self.form_obj.fields.keys()) if f not in rendered_fields])

                if len(other_fieldset.fields):
                    if len(container) and isinstance(container[0], Column):
                        container[0].fields.append(other_fieldset)
                    else:
                        container.append(other_fieldset)

        return layout

    @pluginhook
    def get_model_form(self, **kwargs):
        """
        根据 Model 返回 Form 类，用来显示表单。
        """

        exclude = list(self.exclude)
        if self.exclude is None and hasattr(self.form, '_meta') and self.form._meta.exclude:
            # 如果 :attr:`~website.view.website.ModelViewTemplate.exclude` 是 None，并且 form 的 Meta.exclude 不为空，
            # 则使用 form 的 Meta.exclude
            exclude.extend(self.form._meta.exclude)
        # 如果 exclude 是空列表，那么就设为 None
        # exclude = exclude or None
        defaults = {
            "form": self.form,
            "fields": self.fields and list(self.fields) or None,
            "exclude": exclude,
        }
        defaults.update(kwargs)
        return modelform_factory(self.model, **defaults)

    @pluginhook
    def get_form_helper(self):
        """
        取得 Crispy Form 需要的 FormHelper。具体信息可以参看 `Crispy Form 文档 <http://django-crispy-forms.readthedocs.org/en/latest/tags.html#crispy-tag>`_
        """
        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        layout = self.get_form_layout()
        # 替换所有的字段为 InlineShowField
        replace_field_to_value(layout, self.get_field_result)
        helper.add_layout(layout)
        helper.filter(
            str, max_level=20).wrap(ShowField, view=self)

        # 处理只读字段
        readonly_fields = self.get_readonly_fields()
        if readonly_fields:
            # 使用 :class:`website.view.detail.DetailViewMixin` 来显示只读字段的内容
            detail = self.getmodelviewclass(
                DetailViewMixin, self.model, self.form_obj.instance)
            for field in readonly_fields:
                # 替换只读字段
                helper[field].wrap(ShowField, detail=detail)

        return helper

    @pluginhook
    def get_readonly_fields(self):
        """
        返回只读字段，子类或 iview 可以复写该方法
        """
        return self.readonly_fields

    @csrf_protect_m
    @pluginhook
    def get(self, request, *args, **kwargs):
        form = self.get_model_form()
        self.form_obj = form(instance=self.obj)
        helper = self.get_form_helper()
        if helper:
            self.form_obj.helper = helper

        return self.get_response()

    @pluginhook
    def get_context(self):
        """
        **Context Params** :

            ``form`` : 用于显示数据的 Form 对象

            ``object`` : 要显示的 Model 对象
        """
        new_context = {
            'title': _('%s 详细') % force_str(self.opts.verbose_name),
            'form': self.form_obj,

            'object': self.obj,

            'has_change_permission': self.has_change_permission(self.obj),
            'has_delete_permission': self.has_delete_permission(self.obj),

            'content_type_id': ContentType.objects.get_for_model(self.model).id,
        }

        context = super(DetailView, self).get_context()
        context.update(new_context)
        return context

    @pluginhook
    def get_breadcrumb(self):
        bcs = super(DetailView, self).get_breadcrumb()
        item = {'title': force_str(self.obj)}
        if self.has_view_permission():
            item['url'] = self.model_admin_url('detail', self.obj.pk)
        bcs.append(item)
        return bcs

    @pluginhook
    def get_media(self):
        """
        返回列表页面的 Media, 该页面添加了 ``form.css`` 文件
        """
        return super().get_media() + self.form_obj.media + \
               self.vendor('website.page.form.js', 'website.form.css')

    @pluginhook
    def get_field_result(self, field_name):
        """
        返回包含该字段内容的 :class:`ResultField` 实例.
        """
        return ResultField(self.obj, field_name, self)

    @pluginhook
    def get_response(self, *args, **kwargs):
        """
        返回 HttpResponse , 插件可以复写该方法返回特定的 HttpResponse
        """
        context = self.get_context()
        context.update(kwargs or {})

        return TemplateResponse(self.request, self.detail_template or
                                self.get_template_list(
                                    'views/model_detail.tpl'),
                                context)


class DetailViewMixin(DetailView):

    def init_request(self, obj):
        self.obj = obj
        self.org_obj = obj


class DeleteView(ModelViewTemplate):
    delete_confirmation_template = None

    def init_request(self, object_id, *args, **kwargs):
        """
        初始化操作。根据传入的 ``object_id`` 取得要被删除的数据对象，而后进行权限判断
        """
        self.obj = self.get_object(unquote(object_id))

        if not self.has_delete_permission(self.obj):
            raise PermissionDenied

        if self.obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {
                'name': force_str(self.opts.verbose_name), 'key': escape(object_id)})

        using = router.db_for_write(self.model)  # 取得所用db
        # 生成 deleted_objects, 存有所有即将被删除的关联数据
        (self.deleted_objects, self.perms_needed, self.protected) = get_deleted_objects(
            [self.obj], self.opts, self.request.user, self.website, using)

    @csrf_protect_m
    @pluginhook
    def get(self, request, object_id):
        context = self.get_context()

        return TemplateResponse(request, self.delete_confirmation_template or
                                self.get_template_list("views/model_delete_confirm.tpl"), context)

    @csrf_protect_m
    @dutils.commit_on_success
    @pluginhook
    def post(self, request, object_id):
        if self.perms_needed:
            raise PermissionDenied

        self.delete_model()

        response = self.post_response()

        if isinstance(response, str):
            # 如果返回字符串，说明是一个url，跳转到该页面
            return HttpResponseRedirect(response)
        else:
            return response

    @pluginhook
    def delete_model(self):
        """
        删除 ``self.obj``
        """
        self.do_delete()

    def do_delete(self):
        if self.log:
            self.log_deletion(self.request, self.obj)
        self.obj.delete()

    @pluginhook
    def get_context(self):
        """
        **Context Params**:

            ``title`` : 确认删除的标题，如果您没有权限删除的话，会提示无法删除

            ``object`` : 要被删除的对象

            ``deleted_objects`` : 关联被删除的所有数据对象

            ``perms_lacking`` : 缺少的权限

            ``protected`` : 被保护的数据，无法被删除的数据对象
        """
        if self.perms_needed or self.protected:
            title = _("Cannot delete %(name)s") % {"name":
                                                       force_str(self.opts.verbose_name)}
        else:
            title = _("Are you sure?")

        new_context = {
            "title": title,
            "object": self.obj,
            "deleted_objects": self.deleted_objects,
            "perms_lacking": self.perms_needed,
            "protected": self.protected,
        }
        context = super(DeleteView, self).get_context()
        context.update(new_context)
        return context

    @pluginhook
    def get_breadcrumb(self):
        bcs = super(DeleteView, self).get_breadcrumb()
        bcs.append({
            'title': force_str(self.obj),
            'url': self.get_object_url(self.obj)
        })
        item = {'title': _('Delete')}
        if self.has_delete_permission():
            item['url'] = self.model_admin_url('delete', self.obj.pk)
        bcs.append(item)

        return bcs

    @pluginhook
    def post_response(self):
        """
        删除成功后的操作。首先提示用户信息，而后根据用户权限做跳转，如果用户有列表产看权限就跳转到列表页面，否则跳到网站首页。
        """
        self.message_user(_('The %(name)s "%(obj)s" was deleted successfully.') %
                          {'name': force_str(self.opts.verbose_name), 'obj': force_str(self.obj)}, 'success')

        if not self.has_view_permission():
            return self.get_site_url('index')
        return self.model_admin_url('changelist')

    def log_deletion(self, request, object):
        """
        删除对象日志
        """
        from django.contrib.baseadmin.models import LogEntry, DELETION
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(self.model).pk,
            object_id=object.pk,
            object_repr=force_text(object),
            action_flag=DELETION
        )


class InlineStyleManager(object):
    inline_styles = {}

    def register_style(self, name, style):
        self.inline_styles[name] = style

    def get_style(self, name='stacked'):
        return self.inline_styles.get(name)


style_manager = InlineStyleManager()


class InlineStyle(object):
    template = 'website/edit_inline/stacked.tpl'

    def __init__(self, view, formset):
        self.view = view
        self.formset = formset
        self.box_tpl = self.view.website.style_adminlte and 'website/includes/box_ext.tpl' or 'website/includes/box.tpl'

    def update_layout(self, helper):
        pass

    def get_attrs(self):
        return {'box_tpl': self.box_tpl}


class OneInlineStyle(InlineStyle):
    template = 'website/edit_inline/one.tpl'


class NewInlineStyle(InlineStyle):
    template = 'website/edit_inline/new.tpl'


class AccInlineStyle(InlineStyle):
    template = 'website/edit_inline/accordion.tpl'


class TabInlineStyle(InlineStyle):
    template = 'website/edit_inline/tab.tpl'


class TableInlineStyle(InlineStyle):
    template = 'website/edit_inline/tabular.tpl'

    def update_layout(self, helper):
        helper.add_layout(
            Layout(*[TDField(f) for f in list(self.formset[0].fields.keys())]))

    def get_attrs(self):
        fields = []
        readonly_fields = []
        if len(self.formset):
            fields = [f for k, f in list(self.formset[0].fields.items()) if k != DELETION_FIELD_NAME]
            readonly_fields = [f for f in getattr(self.formset[0], 'readonly_fields', [])]
        return {
            'fields': fields,
            'readonly_fields': readonly_fields,
            'box_tpl': self.box_tpl
        }


class GatherInlineStyle(TableInlineStyle):
    template = 'website/edit_inline/gather.tpl'


style_manager.register_style('stacked', InlineStyle)

style_manager.register_style("one", OneInlineStyle)

style_manager.register_style("new", NewInlineStyle)

style_manager.register_style("accordion", AccInlineStyle)

style_manager.register_style("tab", TabInlineStyle)

style_manager.register_style("table", TableInlineStyle)

style_manager.register_style("gather", GatherInlineStyle)


class InlineFormViewTemplate(ModelFormViewTemplate):
    fk_name = None
    formset = BaseInlineFormSet
    extra = 1
    max_num = None
    can_delete = True
    view = None
    style = 'table'

    def init(self, view):
        self.view = view
        self.parent_model = view.model
        self.org_obj = getattr(view, 'org_obj', None)
        self.model_instance = self.org_obj or view.model()
        return self

    @pluginhook
    def get_formset(self, **kwargs):
        """返回 BaseInlineFormSet 类"""

        exclude = list(self.exclude)
        exclude.extend(self.get_readonly_fields())
        if self.exclude is None and hasattr(self.form, '_meta') and self.form._meta.exclude:
            # Take the custom ModelForm's Meta.exclude into account only if the
            # InlineFormViewTemplate doesn't define its own.
            exclude.extend(self.form._meta.exclude)
        # if exclude is an empty list we use None, since that's the actual
        # default
        # exclude = exclude or None
        can_delete = self.can_delete and self.has_delete_permission()
        defaults = {
            "form": self.form,
            "formset": self.formset,
            "fk_name": self.fk_name,
            "exclude": exclude,
            "formfield_callback": self.formfield_for_dbfield,
            "extra": self.extra,
            "max_num": self.max_num,
            "can_delete": can_delete,
        }
        defaults.update(kwargs)
        return inlineformset_factory(self.parent_model, self.model, **defaults)

    @pluginhook
    def instance_form(self, **kwargs):
        '''
        返回formset对象实例
        '''
        formset = self.get_formset(**kwargs)
        attrs = {
            'instance': self.model_instance,
            'queryset': self.style == 'new' and [] or self.queryset()  # 关键点
        }
        if self.request_method == 'post':
            attrs.update({
                'data': self.request.POST, 'files': self.request.FILES,
                'save_as_new': "_saveasnew" in self.request.POST
            })
        instance = formset(**attrs)
        instance.view = self

        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        # override form method to prevent render csrf_token in inline forms, see template 'bootstrap/whole_uni_form.tpl'
        helper.form_method = 'get'

        style = style_manager.get_style(
            'one' if self.max_num == 1 else self.style)(self, instance)
        style.name = self.style

        if len(instance):
            layout = copy.deepcopy(self.form_layout)

            if layout is None:
                layout = Layout(*list(instance[0].fields.keys()))
            elif type(layout) in (list, tuple) and len(layout) > 0:
                layout = Layout(*layout)

                rendered_fields = [i[1] for i in layout.get_field_names()]
                layout.extend([f for f in list(instance[0]
                                               .fields.keys()) if f not in rendered_fields])

            helper.add_layout(layout)
            style.update_layout(helper)

            # replace delete field with Dynamic field, for hidden delete field when instance is NEW.
            helper[DELETION_FIELD_NAME].wrap(DeleteField)

        instance.helper = helper
        instance.style = style

        readonly_fields = self.get_readonly_fields()
        if readonly_fields:
            for form in instance:
                form.readonly_fields = []
                inst = form.save(commit=False)
                if inst:
                    for readonly_field in readonly_fields:
                        value = None
                        label = None
                        if readonly_field in inst._meta.get_all_field_names():
                            label = inst._meta.get_field_by_name(readonly_field)[0].verbose_name
                            value = str(getattr(inst, readonly_field))
                        elif inspect.ismethod(getattr(inst, readonly_field, None)):
                            value = getattr(inst, readonly_field)()
                            label = getattr(getattr(inst, readonly_field), 'verbose_name', readonly_field)
                        elif inspect.ismethod(getattr(self, readonly_field, None)):
                            value = getattr(self, readonly_field)(inst)
                            label = getattr(getattr(self, readonly_field), 'verbose_name', readonly_field)
                        if value:
                            form.readonly_fields.append({'label': label, 'contents': value})
        return instance

    def has_auto_field(self, form):
        if form._meta.model._meta.has_auto_field:
            return True
        for parent in form._meta.model._meta.get_parent_list():
            if parent._meta.has_auto_field:
                return True
        return False

    def queryset(self):
        queryset = super(InlineFormViewTemplate, self).queryset()
        if self.style == 'new':
            return queryset.none()
        if not self.has_change_permission() and not self.has_view_permission():
            queryset = queryset.none()
        return queryset

    def has_add_permission(self):
        if self.opts.auto_created:
            return self.has_change_permission()
        return self.user.has_perm(
            self.opts.app_label + '.add_' + self.opts.object_name.lower())

    def has_change_permission(self):
        opts = self.opts
        if opts.auto_created:
            for field in opts.fields:
                if field.remote_field and field.remote_field.model != self.parent_model:
                    opts = field.remote_field.model._meta
                    break
        return self.user.has_perm(
            opts.app_label + '.change_' + opts.object_name.lower())

    def has_delete_permission(self):
        if self.opts.auto_created:
            return self.has_change_permission()
        return self.user.has_perm(
            self.opts.app_label + '.delete_' + self.opts.object_name.lower())


class GenericInlineModelView(InlineFormViewTemplate):
    ct_field = "content_type"
    ct_fk_field = "object_id"

    formset = dutils.BaseGenericInlineFormSet

    def get_formset(self, **kwargs):
        exclude = list(self.exclude)
        exclude.extend(self.get_readonly_fields())
        if self.exclude is None and hasattr(self.form, '_meta') and self.form._meta.exclude:
            # Take the custom ModelForm's Meta.exclude into account only if the
            # GenericInlineModelView doesn't define its own.
            exclude.extend(self.form._meta.exclude)
        # exclude = exclude or None
        can_delete = self.can_delete and self.has_delete_permission()
        defaults = {
            "ct_field": self.ct_field,
            "fk_field": self.ct_fk_field,
            "form": self.form,
            "formfield_callback": self.formfield_for_dbfield,
            "formset": self.formset,
            "extra": self.extra,
            "can_delete": can_delete,
            "can_order": False,
            "max_num": self.max_num,
            "exclude": exclude
        }
        defaults.update(kwargs)
        return dutils.generic_inlineformset_factory(self.model, **defaults)


class DashboardViewTemplate(LayoutViewTemplate):
    menu_show = False
    widget_customiz = True
    widgets = []
    title = _("Dashboard")
    icon = None
    app_label = None
    template = 'website/views/dashboard.tpl'

    def get_page_id(self):
        return self.request.path

    def get_portal_key(self):
        return "dashboard:%s:pos" % self.get_page_id()

    @pluginhook
    def get_widget(self, widget_or_id, data=None):
        '''
        实例化widget
        '''
        try:
            if isinstance(widget_or_id, UserComponent):
                widget = widget_or_id
            else:
                widget = UserComponent.objects.get(user=self.user, page_id=self.get_page_id(), id=widget_or_id)
            wid = componentmanager.get(widget.widget_type)

            class widget_with_perm(wid):
                def context(self, context):
                    super(widget_with_perm, self).context(context)
                    context.update({'has_change_permission': self.request.user.has_perm('website.change_userwidget')})

            wid_instance = widget_with_perm(self, data or widget.get_value())
            return wid_instance
        except UserComponent.DoesNotExist:
            return None

    @pluginhook
    def get_init_widget(self):
        '''
        初始化获取要显示的 widgets
        注: widget_customiz=True 时才会 save
        '''
        portal = []
        widgets = self.widgets
        for col in widgets:
            portal_col = []
            for opts in col:
                try:
                    widget = UserComponent(user=self.user, page_id=self.get_page_id(), widget_type=opts['type'])
                    widget.set_value(opts)
                    if self.widget_customiz:
                        widget.save()
                    else:
                        widget.id = 0
                    portal_col.append(self.get_widget(widget))
                except (PermissionDenied, WidgetDataError):
                    if self.widget_customiz:
                        widget.delete()
                    continue
            portal.append(portal_col)
        if self.widget_customiz:
            UserSetting(
                user=self.user, key="dashboard:%s:pos" % self.get_page_id(),
                value='|'.join([','.join([str(w.id) for w in col]) for col in portal])).save()

        return portal

    @pluginhook
    def get_widgets(self):
        '''
        构造要显示的 widgets
        '''
        if self.widget_customiz:
            portal_pos = UserSetting.objects.filter(
                user__id=self.user.id, key=self.get_portal_key())
            if len(portal_pos):
                portal_pos = portal_pos[0].value
                widgets = []

                if portal_pos:
                    user_widgets = dict([(uw.id, uw) for uw in
                                         UserComponent.objects.filter(user__id=self.user.id,
                                                                      page_id=self.get_page_id())])
                    for col in portal_pos.split('|'):
                        ws = []
                        for wid in col.split(','):
                            if not wid: continue
                            try:
                                widget = user_widgets.get(int(wid))
                                if widget:
                                    ws.append(self.get_widget(widget))
                            except Exception as e:
                                import logging
                                logging.error(e, exc_info=True)
                        widgets.append(ws)

                return widgets
            else:
                # 查不到则初始化获取
                return self.get_init_widget()
        else:
            # 不允许自定义则每次都初始化获取
            return self.get_init_widget()

    @pluginhook
    def get_title(self):
        return self.title

    @pluginhook
    def get_context(self):
        new_context = {
            'base_template': self.website.style_adminlte and 'website/adminlte.tpl' or 'website/base.bootstrap.content.noleft.tpl',
            'title': self.get_title(),
            'icon': self.icon,
            'portal_key': self.get_portal_key(),
            'columns': [('col-sm-%d' % int(12 / len(self.widgets)), ws) for ws in self.widgets],
            'has_add_widget_permission': self.has_model_perm(UserComponent, 'add') and self.widget_customiz,
            'add_widget_url': self.get_site_url(
                '%s_%s_add' % (UserComponent._meta.app_label, UserComponent._meta.model_name)) +
                              "?user=%s&page_id=%s&_redirect=%s" % (
                                  self.user.id, self.get_page_id(), urlquote(self.request.get_full_path()))
        }
        context = super(DashboardViewTemplate, self).get_context()
        context.update(new_context)
        return context

    @never_cache
    def get(self, request, *args, **kwargs):
        self.widgets = self.get_widgets()
        return self.template_response(self.template, self.get_context())

    @csrf_protect_m
    def post(self, request, *args, **kwargs):
        if 'id' in request.POST:
            widget_id = request.POST['id']
            if request.POST.get('_delete', None) != 'on':
                widget = self.get_widget(widget_id, request.POST.copy())
                widget.save()
            else:
                try:
                    widget = UserComponent.objects.get(
                        user=self.user, page_id=self.get_page_id(), id=widget_id)
                    widget.delete()
                    try:
                        portal_pos = UserSetting.objects.get(user=self.user,
                                                             key="dashboard:%s:pos" % self.get_page_id())
                        pos = [[w for w in col.split(',') if w != str(
                            widget_id)] for col in portal_pos.value.split('|')]
                        portal_pos.value = '|'.join([','.join(col) for col in pos])
                        portal_pos.save()
                    except Exception:
                        pass
                except UserComponent.DoesNotExist:
                    pass

        return self.get(request)

    @pluginhook
    def get_media(self):
        media = super(DashboardViewTemplate, self).get_media() + \
                self.vendor('website.page.dashboard.js', 'website.page.dashboard.css')
        if self.widget_customiz:
            media = media + self.vendor('website.plugin.portal.js')
        for ws in self.widgets:
            for widget in ws:
                media = media + widget.media()
        return media


class ModelDashboardView(DashboardViewTemplate, ModelViewTemplate):
    title = _("%s Dashboard")

    def get_page_id(self):
        return 'model:%s/%s' % self.model_info

    @pluginhook
    def get_title(self):
        return self.title % force_str(self.obj)

    def init_request(self, object_id, *args, **kwargs):
        self.obj = self.get_object(unquote(object_id))

        if not self.has_view_permission(self.obj):
            raise PermissionDenied

        if self.obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') %
                          {'name': force_str(self.opts.verbose_name), 'key': escape(object_id)})

    @pluginhook
    def get_context(self):
        new_context = {
            'has_change_permission': self.has_change_permission(self.obj),
            'object': self.obj,
        }
        context = DashboardViewTemplate.get_context(self)
        context.update(ModelViewTemplate.get_context(self))
        context.update(new_context)
        return context

    @never_cache
    def get(self, request, *args, **kwargs):
        self.widgets = self.get_widgets()
        return self.template_response(self.get_template_list('views/model_dashboard.tpl'), self.get_context())


class ModuleDashboardView(DashboardViewTemplate):
    title = _("%s Dashboard")
    icon = "fa fa-dashboard"
    base_template = 'website/bootstrap3.tpl'

    def get_page_id(self):
        return 'app:%s' % self.app_label

    def get_title(self):
        mod = self.website.modules[self.app_label]
        return self.title % force_str(getattr(mod, 'verbose_name', self.app_label))

    def set_widgets(self, context):
        # 设置 self.widgets
        nav_menu = context['nav_menu']
        widgets = [
            [],
            []
        ]
        flag = False
        for item in nav_menu:
            widget = {"type": "qbutton", "title": item['title'], "btns": []}
            for sitem in item['menus']:
                widget['btns'].append({'title': sitem['title'], 'url': sitem['url'], 'icon': sitem['icon']})
            widgets[int(flag)].append(widget)
            flag = not flag
        self.widgets = widgets

    @pluginhook
    def get_context(self):
        context = super(DashboardViewTemplate, self).get_context()
        self.set_widgets(context)
        self.widgets = self.get_widgets()
        new_context = {
            'base_template': self.website.style_adminlte and 'website/adminlte.tpl' or 'website/bootstrap3.tpl',
            'title': self.get_title(),
            'icon': self.icon,
            'portal_key': self.get_portal_key(),
            'columns': [('col-sm-%d' % int(12 / len(self.widgets)), ws) for ws in self.widgets],
            'has_add_widget_permission': self.has_model_perm(UserComponent, 'add') and self.widget_customiz,
            'add_widget_url': self.get_site_url(
                '%s_%s_add' % (UserComponent._meta.app_label, UserComponent._meta.model_name)) +
                              "?user=%s&page_id=%s&_redirect=%s" % (
                                  self.user.id, self.get_page_id(), urlquote(self.request.get_full_path()))
        }
        context.update(new_context)
        return context

    @never_cache
    def get(self, request, *args, **kwargs):
        return self.template_response(self.template, self.get_context())


class IFrameViewTemplate(LayoutViewTemplate):
    title = _("Main Dashboard")
    template = 'website/main.tpl'
    app_label = None
    menu_show = False

    @pluginhook
    def get_context(self):
        context = super(LayoutViewTemplate, self).get_context()

        nav_menu = self.get_nav_menu()
        self.website = self.website
        context.update({
            'template': template,
            'menu_template': configs.BUILDIN_STYLES['ext'],
            'nav_menu': nav_menu,
            # 'site_menu': hasattr(self, 'app_label') and self.website.get_select_menu(self.app_label) or [],
            'site_title': self.website.style_title,
            'site_footer': self.website.style_footer,
            # 'breadcrumbs': self.get_breadcrumb(),
            'head_fix': self.website.style_fixhead,
            'adminlte': self.website.style_adminlte,
            # 'head_fix': True,
        })
        return context

    @never_cache
    def get(self, request, *args, **kwargs):
        return self.template_response(self.template, self.get_context())


class FormWizard(object):
    # The HTML (and POST data) field name for the "step" variable.
    step_field_name = "wizard_step"

    # METHODS SUBCLASSES SHOULDN'T OVERRIDE ###################################

    def __init__(self, form_list, initial=None):
        """
        Start a new wizard with a list of forms.

        form_list should be a list of Form classes (not instances).
        """
        self.form_list = form_list[:]
        self.initial = initial or {}

        # Dictionary of extra template context variables.
        self.extra_context = {}

        # A zero-based counter keeping track of which step we're in.
        self.step = 0

        import warnings
        warnings.warn(
            'Old-style form wizards have been deprecated; use the class-based '
            'views in django.contrib.formtools.wizard.receivers instead.',
            DeprecationWarning)

    def __repr__(self):
        return "step: %d\nform_list: %s\ninitial_data: %s" % (self.step, self.form_list, self.initial)

    def get_form(self, step, data=None):
        "Helper method that returns the Form instance for the given step."
        # Sanity check.
        if step >= self.num_steps():
            raise Http404('Step %s does not exist' % step)
        return self.form_list[step](data, prefix=self.prefix_for_step(step), initial=self.initial.get(step, None))

    def num_steps(self):
        "Helper method that returns the number of steps."
        # You might think we should just set "self.num_steps = len(form_list)"
        # in __init__(), but this calculation needs to be dynamic, because some
        # hook methods might alter self.form_list.
        return len(self.form_list)

    def _check_security_hash(self, token, request, form):
        expected = self.security_hash(request, form)
        return constant_time_compare(token, expected)

    @method_decorator(csrf_protect)
    def __call__(self, request, *args, **kwargs):
        """
        Main method that does all the hard work, conforming to the django view
        interface.
        """
        if 'extra_context' in kwargs:
            self.extra_context.update(kwargs['extra_context'])
        current_step = self.get_current_or_first_step(request, *args, **kwargs)
        self.parse_params(request, *args, **kwargs)

        # Validate and process all the previous forms before instantiating the
        # current step's form in case self.process_step makes changes to
        # self.form_list.

        # If any of them fails validation, that must mean the validator relied
        # on some other input, such as an external Web website.

        # It is also possible that alidation might fail under certain attack
        # situations: an attacker might be able to bypass previous stages, and
        # generate correct security hashes for all the skipped stages by virtue
        # of:
        #  1) having filled out an identical form which doesn't have the
        #     validation (and does something different at the end),
        #  2) or having filled out a previous version of the same form which
        #     had some validation missing,
        #  3) or previously having filled out the form when they had more
        #     privileges than they do now.
        #
        # Since the hashes only take into account values, and not other other
        # validation the form might do, we must re-do validation now for
        # security reasons.
        previous_form_list = []
        for i in range(current_step):
            f = self.get_form(i, request.POST)
            if not self._check_security_hash(request.POST.get("hash_%d" % i, ''),
                                             request, f):
                return self.render_hash_failure(request, i)

            if not f.is_valid():
                return self.render_revalidation_failure(request, i, f)
            else:
                self.process_step(request, f, i)
                previous_form_list.append(f)

        # Process the current step. If it's valid, go to the next step or call
        # done(), depending on whether any steps remain.
        if request.method == 'POST':
            form = self.get_form(current_step, request.POST)
        else:
            form = self.get_form(current_step)

        if form.is_valid():
            self.process_step(request, form, current_step)
            next_step = current_step + 1

            if next_step == self.num_steps():
                return self.done(request, previous_form_list + [form])
            else:
                form = self.get_form(next_step)
                self.step = current_step = next_step

        return self.render(form, request, current_step)

    def render(self, form, request, step, context=None):
        "Renders the given Form object, returning an HttpResponse."
        old_data = request.POST
        prev_fields = []
        if old_data:
            hidden = HiddenInput()
            # Collect all data from previous steps and render it as HTML hidden fields.
            for i in range(step):
                old_form = self.get_form(i, old_data)
                hash_name = 'hash_%s' % i
                prev_fields.extend([bf.as_hidden() for bf in old_form])
                prev_fields.append(
                    hidden.render(hash_name, old_data.get(hash_name, self.security_hash(request, old_form))))
        return self.render_template(request, form, ''.join(prev_fields), step, context)

    # METHODS SUBCLASSES MIGHT OVERRIDE IF APPROPRIATE ########################

    def prefix_for_step(self, step):
        "Given the step, returns a Form prefix to use."
        return str(step)

    def render_hash_failure(self, request, step):
        """
        Hook for rendering a template if a hash check failed.

        step is the step that failed. Any previous step is guaranteed to be
        valid.

        This default implementation simply renders the form for the given step,
        but subclasses may want to display an error message, etc.
        """
        return self.render(self.get_form(step), request, step, context={'wizard_error': _(
            'We apologize, but your form has expired. Please continue filling out the form from this page.')})

    def render_revalidation_failure(self, request, step, form):
        """
        Hook for rendering a template if final revalidation failed.

        It is highly unlikely that this point would ever be reached, but See
        the comment in __call__() for an explanation.
        """
        return self.render(form, request, step)

    def security_hash(self, request, form):
        """
        Calculates the security hash for the given HttpRequest and Form instances.

        Subclasses may want to take into account request-specific information,
        such as the IP address.
        """
        return form_hmac(form)

    def get_current_or_first_step(self, request, *args, **kwargs):
        """
        Given the request object and whatever *args and **kwargs were passed to
        __call__(), returns the current step (which is zero-based).

        Note that the result should not be trusted. It may even be a completely
        invalid number. It's not the job of this method to validate it.
        """
        if not request.POST:
            return 0
        try:
            step = int(request.POST.get(self.step_field_name, 0))
        except ValueError:
            return 0
        return step

    def parse_params(self, request, *args, **kwargs):
        """
        Hook for setting some state, given the request object and whatever
        *args and **kwargs were passed to __call__(), sets some state.

        This is called at the beginning of __call__().
        """
        pass

    def get_template(self, step):
        """
        Hook for specifying the name of the template to use for a given step.

        Note that this can return a tuple of template names if you'd like to
        use the template system's select_template() hook.
        """
        return 'forms/wizard.tpl'

    def render_template(self, request, form, previous_fields, step, context=None):
        """
        Renders the template for the given step, returning an HttpResponse object.

        Override this method if you want to add a custom context, return a
        different MIME type, etc. If you only need to override the template
        name, use get_template() instead.

        The template will be rendered with the following context:
            step_field -- The name of the hidden field containing the step.
            step0      -- The current step (zero-based).
            step       -- The current step (one-based).
            step_count -- The total number of steps.
            form       -- The Form instance for the current step (either empty
                          or with errors).
            previous_fields -- A string representing every previous data field,
                          plus hashes for completed forms, all in the form of
                          hidden fields. Note that you'll need to run this
                          through the "safe" template filter, to prevent
                          auto-escaping, because it's raw HTML.
        """
        context = context or {}
        context.update(self.extra_context)
        return render_to_response(self.get_template(step), dict(context,
                                                                step_field=self.step_field_name,
                                                                step0=step,
                                                                step=step + 1,
                                                                step_count=self.num_steps(),
                                                                form=form,
                                                                previous_fields=previous_fields
                                                                ), context_instance=RequestContext(request))

    def process_step(self, request, form, step):
        """
        Hook for modifying the FormWizard's internal state, given a fully
        validated Form object. The Form is guaranteed to have clean, valid
        data.

        This method should *not* modify any of that data. Rather, it might want
        to set self.extra_context or dynamically alter self.form_list, based on
        previously submitted forms.

        Note that this method is called every time a page is rendered for *all*
        submitted steps.
        """
        pass

    # METHODS SUBCLASSES MUST OVERRIDE ########################################

    def done(self, request, form_list):
        """
        Hook for doing something with the validated data. This is responsible
        for the final processing.

        form_list is a list of Form instances, each containing clean, valid
        data.
        """
        raise NotImplementedError(
            "Your %s class has not defined a done() method, which is required." % self.__class__.__name__)


def form_hmac(form):
    """
    Calculates a security hash for the given Form instance.
    """
    data = []
    for bf in form:
        # Get the value from the form data. If the form allows empty or hasn't
        # changed then don't call clean() to avoid trigger validation errors.
        if form.empty_permitted and not form.has_changed():
            value = bf.data or ''
        else:
            value = bf.field.clean(bf.data) or ''
        if isinstance(value, six.string_types):
            value = value.strip()
        data.append((bf.name, value))

    pickled = pickle.dumps(data, pickle.HIGHEST_PROTOCOL)
    key_salt = 'django.contrib.formtools'
    return salted_hmac(key_salt, pickled).hexdigest()


def normalize_name(name):
    """
    Converts camel-case style names into underscore seperated words. Example::

        >>> normalize_name('oneTwoThree')
        'one_two_three'
        >>> normalize_name('FourFiveSix')
        'four_five_six'

    """
    new = re.sub('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))', '_\\1', name)
    return new.lower().strip('_')


class StepsHelper(object):

    def __init__(self, wizard):
        self._wizard = wizard

    def __dir__(self):
        return self.all

    def __len__(self):
        return self.count

    def __repr__(self):
        return '<StepsHelper for %s (steps: %s)>' % (self._wizard, self.all)

    @property
    def all(self):
        "Returns the names of all steps/forms."
        return list(self._wizard.get_form_list())

    @property
    def count(self):
        "Returns the total number of steps/forms in this the wizard."
        return len(self.all)

    @property
    def current(self):
        """
        Returns the current step. If no current step is stored in the
        storage backend, the first step will be returned.
        """
        return self._wizard.storage.current_step or self.first

    @property
    def first(self):
        "Returns the name of the first step."
        return self.all[0]

    @property
    def last(self):
        "Returns the name of the last step."
        return self.all[-1]

    @property
    def next(self):
        "Returns the next step."
        return self._wizard.get_next_step()

    @property
    def prev(self):
        "Returns the previous step."
        return self._wizard.get_prev_step()

    @property
    def index(self):
        "Returns the index for the current step."
        return self._wizard.get_step_index()

    @property
    def step0(self):
        return int(self.index)

    @property
    def step1(self):
        return int(self.index) + 1


class WizardView(TemplateView):
    """
    The WizardView is used to create multi-page forms and handles all the
    storage and validation stuff. The wizard is based on django's generic
    class based views.
    """
    storage_name = None
    form_list = None
    initial_dict = None
    instance_dict = None
    condition_dict = None
    template_name = 'formtools/wizard/wizard_form.tpl'

    def __repr__(self):
        return '<%s: forms: %s>' % (self.__class__.__name__, self.form_list)

    @classonlymethod
    def as_view(cls, *args, **kwargs):
        """
        This method is used within urls.py to create unique wizardview
        instances for every request. We need to override this method because
        we add some kwargs which are needed to make the wizardview usable.
        """
        initkwargs = cls.get_initkwargs(*args, **kwargs)
        return super(WizardView, cls).as_view(**initkwargs)

    @classmethod
    def get_initkwargs(cls, form_list, initial_dict=None,
                       instance_dict=None, condition_dict=None, *args, **kwargs):
        """
        Creates a dict with all needed parameters for the form wizard instances.

        * `form_list` - is a list of forms. The list entries can be single form
          classes or tuples of (`step_name`, `form_class`). If you pass a list
          of forms, the wizardview will convert the class list to
          (`zero_based_counter`, `form_class`). This is needed to access the
          form for a specific step.
        * `initial_dict` - contains a dictionary of initial data dictionaries.
          The key should be equal to the `step_name` in the `form_list` (or
          the str of the zero based counter - if no step_names added in the
          `form_list`)
        * `instance_dict` - contains a dictionary whose values are model
          instances if the step is based on a ``ModelForm`` and querysets if
          the step is based on a ``ModelFormSet``. The key should be equal to
          the `step_name` in the `form_list`. Same rules as for `initial_dict`
          apply.
        * `condition_dict` - contains a dictionary of boolean values or
          callables. If the value of for a specific `step_name` is callable it
          will be called with the wizardview instance as the only argument.
          If the return value is true, the step's form will be used.
        """
        kwargs.update({
            'initial_dict': initial_dict or {},
            'instance_dict': instance_dict or {},
            'condition_dict': condition_dict or {},
        })
        init_form_list = SortedDict()

        assert len(form_list) > 0, 'at least one form is needed'

        # walk through the passed form list
        for i, form in enumerate(form_list):
            if isinstance(form, (list, tuple)):
                # if the element is a tuple, add the tuple to the new created
                # sorted dictionary.
                init_form_list[six.text_type(form[0])] = form[1]
            else:
                # if not, add the form with a zero based counter as unicode
                init_form_list[six.text_type(i)] = form

        # walk through the new created list of forms
        for form in six.itervalues(init_form_list):
            if issubclass(form, formsets.BaseFormSet):
                # if the element is based on BaseFormSet (FormSet/ModelFormSet)
                # we need to override the form variable.
                form = form.form
            # check if any form contains a FileField, if yes, we need a
            # file_storage added to the wizardview (by subclassing).
            for field in six.itervalues(form.base_fields):
                if (isinstance(field, forms.FileField) and
                        not hasattr(cls, 'file_storage')):
                    raise NoFileStorageConfigured(
                        "You need to define 'file_storage' in your "
                        "wizard view in order to handle file uploads.")

        # build the kwargs for the wizardview instances
        kwargs['form_list'] = init_form_list
        return kwargs

    def get_prefix(self, *args, **kwargs):
        # TODO: Add some kind of unique id to prefix
        return normalize_name(self.__class__.__name__)

    def get_form_list(self):
        """
        This method returns a form_list based on the initial form list but
        checks if there is a condition method/value in the condition_list.
        If an entry exists in the condition list, it will call/read the value
        and respect the result. (True means add the form, False means ignore
        the form)

        The form_list is always generated on the fly because condition methods
        could use data from other (maybe previous forms).
        """
        form_list = SortedDict()
        for form_key, form_class in six.iteritems(self.form_list):
            # try to fetch the value from condition list, by default, the form
            # gets passed to the new list.
            condition = self.condition_dict.get(form_key, True)
            if callable(condition):
                # call the value if needed, passes the current instance.
                condition = condition(self)
            if condition:
                form_list[form_key] = form_class
        return form_list

    def dispatch(self, request, *args, **kwargs):
        """
        This method gets called by the routing engine. The first argument is
        `request` which contains a `HttpRequest` instance.
        The request is stored in `self.request` for later use. The storage
        instance is stored in `self.storage`.

        After processing the request using the `dispatch` method, the
        response gets updated by the storage engine (for example add cookies).
        """
        # add the storage engine to the current wizardview instance
        self.prefix = self.get_prefix(*args, **kwargs)
        self.storage = get_storage(self.storage_name, self.prefix, request,
                                   getattr(self, 'file_storage', None))
        self.steps = StepsHelper(self)
        response = super(WizardView, self).dispatch(request, *args, **kwargs)

        # update the response (e.g. adding cookies)
        self.storage.update_response(response)
        return response

    def get(self, request, *args, **kwargs):
        """
        This method handles GET requests.

        If a GET request reaches this point, the wizard assumes that the user
        just starts at the first step or wants to restart the process.
        The data of the wizard will be resetted before rendering the first step.
        """
        self.storage.reset()

        # reset the current step to the first step.
        self.storage.current_step = self.steps.first
        return self.render(self.get_form())

    def post(self, *args, **kwargs):
        """
        This method handles POST requests.

        The wizard will render either the current step (if form validation
        wasn't successful), the next step (if the current step was stored
        successful) or the done view (if no more steps are available)
        """
        # Look for a wizard_goto_step element in the posted data which
        # contains a valid step name. If one was found, render the requested
        # form. (This makes stepping back a lot easier).
        wizard_goto_step = self.request.POST.get('wizard_goto_step', None)
        if wizard_goto_step and wizard_goto_step in self.get_form_list():
            self.storage.current_step = wizard_goto_step
            form = self.get_form(
                data=self.storage.get_step_data(self.steps.current),
                files=self.storage.get_step_files(self.steps.current))
            return self.render(form)

        # Check if form was refreshed
        management_form = ManagementForm(self.request.POST, prefix=self.prefix)
        if not management_form.is_valid():
            raise ValidationError(
                'ManagementForm data is missing or has been tampered.')

        form_current_step = management_form.cleaned_data['current_step']
        if (form_current_step != self.steps.current and
                self.storage.current_step is not None):
            # form refreshed, change current step
            self.storage.current_step = form_current_step

        # get the form for the current step
        form = self.get_form(data=self.request.POST, files=self.request.FILES)

        # and try to validate
        if form.is_valid():
            # if the form is valid, store the cleaned data and files.
            self.storage.set_step_data(self.steps.current, self.process_step(form))
            self.storage.set_step_files(self.steps.current, self.process_step_files(form))

            # check if the current step is the last step
            if self.steps.current == self.steps.last:
                # no more steps, render done view
                return self.render_done(form, **kwargs)
            else:
                # proceed to the next step
                return self.render_next_step(form)
        return self.render(form)

    def render_next_step(self, form, **kwargs):
        """
        This method gets called when the next step/form should be rendered.
        `form` contains the last/current form.
        """
        # get the form instance based on the data from the storage backend
        # (if available).
        next_step = self.steps.__next__
        new_form = self.get_form(next_step,
                                 data=self.storage.get_step_data(next_step),
                                 files=self.storage.get_step_files(next_step))

        # change the stored current step
        self.storage.current_step = next_step
        return self.render(new_form, **kwargs)

    def render_done(self, form, **kwargs):
        """
        This method gets called when all forms passed. The method should also
        re-validate all steps to prevent manipulation. If any form don't
        validate, `render_revalidation_failure` should get called.
        If everything is fine call `done`.
        """
        final_form_list = []
        # walk through the form list and try to validate the data again.
        for form_key in self.get_form_list():
            form_obj = self.get_form(step=form_key,
                                     data=self.storage.get_step_data(form_key),
                                     files=self.storage.get_step_files(form_key))
            if not form_obj.is_valid():
                return self.render_revalidation_failure(form_key, form_obj, **kwargs)
            final_form_list.append(form_obj)

        # render the done view and reset the wizard before returning the
        # response. This is needed to prevent from rendering done with the
        # same data twice.
        done_response = self.done(final_form_list, **kwargs)
        self.storage.reset()
        return done_response

    def get_form_prefix(self, step=None, form=None):
        """
        Returns the prefix which will be used when calling the actual form for
        the given step. `step` contains the step-name, `form` the form which
        will be called with the returned prefix.

        If no step is given, the form_prefix will determine the current step
        automatically.
        """
        if step is None:
            step = self.steps.current
        return str(step)

    def get_form_initial(self, step):
        """
        Returns a dictionary which will be passed to the form for `step`
        as `initial`. If no initial data was provied while initializing the
        form wizard, a empty dictionary will be returned.
        """
        return self.initial_dict.get(step, {})

    def get_form_instance(self, step):
        """
        Returns a object which will be passed to the form for `step`
        as `instance`. If no instance object was provied while initializing
        the form wizard, None will be returned.
        """
        return self.instance_dict.get(step, None)

    def get_form_kwargs(self, step=None):
        """
        Returns the keyword arguments for instantiating the form
        (or formset) on the given step.
        """
        return {}

    def get_form(self, step=None, data=None, files=None):
        """
        Constructs the form for a given `step`. If no `step` is defined, the
        current step will be determined automatically.

        The form will be initialized using the `data` argument to prefill the
        new form. If needed, instance or queryset (for `ModelForm` or
        `ModelFormSet`) will be added too.
        """
        if step is None:
            step = self.steps.current
        # prepare the kwargs for the form instance.
        kwargs = self.get_form_kwargs(step)
        kwargs.update({
            'data': data,
            'files': files,
            'prefix': self.get_form_prefix(step, self.form_list[step]),
            'initial': self.get_form_initial(step),
        })
        if issubclass(self.form_list[step], forms.ModelForm):
            # If the form is based on ModelForm, add instance if available
            # and not previously set.
            kwargs.setdefault('instance', self.get_form_instance(step))
        elif issubclass(self.form_list[step], forms.models.BaseModelFormSet):
            # If the form is based on ModelFormSet, add queryset if available
            # and not previous set.
            kwargs.setdefault('queryset', self.get_form_instance(step))
        return self.form_list[step](**kwargs)

    def process_step(self, form):
        """
        This method is used to postprocess the form data. By default, it
        returns the raw `form.data` dictionary.
        """
        return self.get_form_step_data(form)

    def process_step_files(self, form):
        """
        This method is used to postprocess the form files. By default, it
        returns the raw `form.files` dictionary.
        """
        return self.get_form_step_files(form)

    def render_revalidation_failure(self, step, form, **kwargs):
        """
        Gets called when a form doesn't validate when rendering the done
        view. By default, it changes the current step to failing forms step
        and renders the form.
        """
        self.storage.current_step = step
        return self.render(form, **kwargs)

    def get_form_step_data(self, form):
        """
        Is used to return the raw form data. You may use this method to
        manipulate the data.
        """
        return form.data

    def get_form_step_files(self, form):
        """
        Is used to return the raw form files. You may use this method to
        manipulate the data.
        """
        return form.files

    def get_all_cleaned_data(self):
        """
        Returns a merged dictionary of all step cleaned_data dictionaries.
        If a step contains a `FormSet`, the key will be prefixed with
        'formset-' and contain a list of the formset cleaned_data dictionaries.
        """
        cleaned_data = {}
        for form_key in self.get_form_list():
            form_obj = self.get_form(
                step=form_key,
                data=self.storage.get_step_data(form_key),
                files=self.storage.get_step_files(form_key)
            )
            if form_obj.is_valid():
                if isinstance(form_obj.cleaned_data, (tuple, list)):
                    cleaned_data.update({
                        'formset-%s' % form_key: form_obj.cleaned_data
                    })
                else:
                    cleaned_data.update(form_obj.cleaned_data)
        return cleaned_data

    def get_cleaned_data_for_step(self, step):
        """
        Returns the cleaned data for a given `step`. Before returning the
        cleaned data, the stored values are revalidated through the form.
        If the data doesn't validate, None will be returned.
        """
        if step in self.form_list:
            form_obj = self.get_form(step=step,
                                     data=self.storage.get_step_data(step),
                                     files=self.storage.get_step_files(step))
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

    def get_context_data(self, form, **kwargs):
        """
        Returns the template context for a step. You can overwrite this method
        to add more data for all or some steps. This method returns a
        dictionary containing the rendered form step. Available template
        context variables are:

         * all extra data stored in the storage backend
         * `form` - form instance of the current step
         * `wizard` - the wizard instance itself

        Example:

        .. code-block:: python

            class MyWizard(WizardView):
                def get_context_data(self, form, **kwargs):
                    context = super(MyWizard, self).get_context_data(form=form, **kwargs)
                    if self.steps.current == 'my_step_name':
                        context.update({'another_var': True})
                    return context
        """
        context = super(WizardView, self).get_context_data(form=form, **kwargs)
        context.update(self.storage.extra_data)
        context['wizard'] = {
            'form': form,
            'steps': self.steps,
            'management_form': ManagementForm(prefix=self.prefix, initial={
                'current_step': self.steps.current,
            }),
        }
        return context

    def render(self, form=None, **kwargs):
        """
        Returns a ``HttpResponse`` containing all needed context data.
        """
        form = form or self.get_form()
        context = self.get_context_data(form=form, **kwargs)
        return self.render_to_response(context)

    def done(self, form_list, **kwargs):
        """
        This method must be overridden by a subclass to process to form data
        after processing all steps.
        """
        raise NotImplementedError("Your %s class has not defined a done() "
                                  "method, which is required." % self.__class__.__name__)


class SessionWizardView(WizardView):
    """
    A WizardView with pre-configured SessionStorage backend.
    """
    storage_name = 'django.contrib.formtools.wizard.storage.session.SessionStorage'


class CookieWizardView(WizardView):
    """
    A WizardView with pre-configured CookieStorage backend.
    """
    storage_name = 'django.contrib.formtools.wizard.storage.cookie.CookieStorage'


class NamedUrlWizardView(WizardView):
    """
    A WizardView with URL named steps support.
    """
    url_name = None
    done_step_name = None

    @classmethod
    def get_initkwargs(cls, *args, **kwargs):
        """
        We require a url_name to reverse URLs later. Additionally users can
        pass a done_step_name to change the URL name of the "done" view.
        """
        assert 'url_name' in kwargs, 'URL name is needed to resolve correct wizard URLs'
        extra_kwargs = {
            'done_step_name': kwargs.pop('done_step_name', 'done'),
            'url_name': kwargs.pop('url_name'),
        }
        initkwargs = super(NamedUrlWizardView, cls).get_initkwargs(*args, **kwargs)
        initkwargs.update(extra_kwargs)

        assert initkwargs['done_step_name'] not in initkwargs['form_list'], \
            'step name "%s" is reserved for "done" view' % initkwargs['done_step_name']
        return initkwargs

    def get_step_url(self, step):
        return reverse(self.url_name, kwargs={'step': step})

    def get(self, *args, **kwargs):
        """
        This renders the form or, if needed, does the http redirects.
        """
        step_url = kwargs.get('step', None)
        if step_url is None:
            if 'reset' in self.request.GET:
                self.storage.reset()
                self.storage.current_step = self.steps.first
            if self.request.GET:
                query_string = "?%s" % self.request.GET.urlencode()
            else:
                query_string = ""
            return redirect(self.get_step_url(self.steps.current)
                            + query_string)

        # is the current step the "done" name/view?
        elif step_url == self.done_step_name:
            last_step = self.steps.last
            return self.render_done(self.get_form(step=last_step,
                                                  data=self.storage.get_step_data(last_step),
                                                  files=self.storage.get_step_files(last_step)
                                                  ), **kwargs)

        # is the url step name not equal to the step in the storage?
        # if yes, change the step in the storage (if name exists)
        elif step_url == self.steps.current:
            # URL step name and storage step name are equal, render!
            return self.render(self.get_form(
                data=self.storage.current_step_data,
                files=self.storage.current_step_files,
            ), **kwargs)

        elif step_url in self.get_form_list():
            self.storage.current_step = step_url
            return self.render(self.get_form(
                data=self.storage.current_step_data,
                files=self.storage.current_step_files,
            ), **kwargs)

        # invalid step name, reset to first and redirect.
        else:
            self.storage.current_step = self.steps.first
            return redirect(self.get_step_url(self.steps.first))

    def post(self, *args, **kwargs):
        """
        Do a redirect if user presses the prev. step button. The rest of this
        is super'd from WizardView.
        """
        wizard_goto_step = self.request.POST.get('wizard_goto_step', None)
        if wizard_goto_step and wizard_goto_step in self.get_form_list():
            self.storage.current_step = wizard_goto_step
            return redirect(self.get_step_url(wizard_goto_step))
        return super(NamedUrlWizardView, self).post(*args, **kwargs)

    def get_context_data(self, form, **kwargs):
        """
        NamedUrlWizardView provides the url_name of this wizard in the context
        dict `wizard`.
        """
        context = super(NamedUrlWizardView, self).get_context_data(form=form, **kwargs)
        context['wizard']['url_name'] = self.url_name
        return context

    def render_next_step(self, form, **kwargs):
        """
        When using the NamedUrlWizardView, we have to redirect to update the
        browser's URL to match the shown step.
        """
        next_step = self.get_next_step()
        self.storage.current_step = next_step
        return redirect(self.get_step_url(next_step))

    def render_revalidation_failure(self, failed_step, form, **kwargs):
        """
        When a step fails, we have to redirect the user to the first failing
        step.
        """
        self.storage.current_step = failed_step
        return redirect(self.get_step_url(failed_step))

    def render_done(self, form, **kwargs):
        """
        When rendering the done view, we have to redirect first (if the URL
        name doesn't fit).
        """
        if kwargs.get('step', None) != self.done_step_name:
            return redirect(self.get_step_url(self.done_step_name))
        return super(NamedUrlWizardView, self).render_done(form, **kwargs)


class NamedUrlSessionWizardView(NamedUrlWizardView):
    """
    A NamedUrlWizardView with pre-configured SessionStorage backend.
    """
    storage_name = 'django.contrib.formtools.wizard.storage.session.SessionStorage'


class NamedUrlCookieWizardView(NamedUrlWizardView):
    """
    A NamedUrlFormWizard with pre-configured CookieStorageBackend.
    """
    storage_name = 'django.contrib.formtools.wizard.storage.cookie.CookieStorage'


class UploadView(ViewTemplate):
    csrf = False

    def post(self, request, *args, **kwargs):
        callback = request.GET.get('CKEditorFuncNum')
        try:

            path = "uploads/" + time.strftime("%Y%m%d%H%M%S", time.localtime())
            uploaded_file = request.FILES["upload"]
            file_name = path + "_" + uploaded_file.name
            saved_path = default_storage.save(file_name, uploaded_file)
            url = default_storage.url(saved_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
        res = "<script>window.parent.CKEDITOR.tools.callFunction(" + callback + ",'" + url + "', '');</script>"
        return self.render_text(res)


class UploadDrogImgView(ViewTemplate):
    csrf = False

    def delete(self, request, *args, **kwargs):
        try:
            file = request.GET.get('file') or kwargs.get('file')
            file = file.replace(default_storage.base_url, '')
            default_storage.delete(default_storage.base_location + file)
            success_message = {
                "delete": 1,
            }
            return self.render_json(success_message)
        except:
            import traceback
            traceback.print_exc()
            fail_message = {
                "delete": 0,
            }
            return self.render_json(fail_message)

    def post(self, request, *args, **kwargs):
        try:
            path = "uploads/" + time.strftime("%Y%m%d%H%M%S", time.localtime())
            uploaded_file = request.FILES.get('upload', False) or request.FILES.get('file', False)
            file_name = path + "_" + uploaded_file.name
            saved_path = default_storage.save(file_name, uploaded_file)
            success_message = {
                "uploaded": 1,
                "fileName": uploaded_file.name,
                "url": default_storage.url(saved_path)
            }
            return self.render_json(success_message)
        except:
            import traceback
            traceback.print_exc()
            fail_message = {
                "uploaded": 0,
                "error": {
                    "message": "上传失败"
                }
            }
            return self.render_json(fail_message)


class ActionViewTemplate(ModelViewTemplate):
    action_name = None  # key名，默认为类名
    verbose_name = None
    icon = 'fa fa-tasks'

    model_perm = None  # 模型权限 'view', 'add', 'change', 'delete'
    perm = None  # 自定义权限
    log = False

    @classmethod
    def has_perm(cls, list_view):
        if cls.model_perm:
            perm_code = cls.model_perm
        else:
            perm_code = cls.perm or 'not_setting_perm'
            perm_code = 'auth.' + perm_code
        return list_view.has_permission(perm_code)

    def init_action(self, list_view):
        self.list_view = list_view
        self.website = list_view.website

    def get_redirect_url(self):
        action_return_url = self.request.META['HTTP_REFERER']
        return action_return_url

    def action(self, queryset):
        pass

    @pluginhook
    def do_action(self, queryset):
        return self.action(queryset)


class ActionFormViewTemplate(ActionViewTemplate):
    form = forms.Form
    form_template = 'website/views/model_form_action.tpl'
    action_url = ''

    def get_form_datas(self):
        data = {'initial': self.get_initial_data()}
        if self.request_method == 'post' and '_save' in self.request.POST:
            data.update({'data': self.request.POST, 'files': self.request.FILES})

        else:
            data['initial'].update(self.request.GET)
        return data

    def get_initial_data(self):
        return {}

    @pluginhook
    def get_form_layout(self):
        layout = copy.deepcopy(self.form_layout)
        fields = self.form_obj.fields.keys()

        if layout is None:
            layout = Layout(Container(Col('full',
                                          Fieldset("", *fields, css_class="unsort no_title"), horizontal=True, span=12)
                                      ))
        elif type(layout) in (list, tuple) and len(layout) > 0:
            if isinstance(layout[0], Column):
                fs = layout
            elif isinstance(layout[0], (Fieldset, TabHolder)):
                fs = (Col('full', *layout, horizontal=True, span=12),)
            else:
                fs = (Col('full', Fieldset("", *layout, css_class="unsort no_title"), horizontal=True, span=12),)

            layout = Layout(Container(*fs))

            rendered_fields = [i[1] for i in layout.get_field_names()]
            container = layout[0].fields
            other_fieldset = Fieldset(_('Other Fields'), *[f for f in fields if f not in rendered_fields])

            if len(other_fieldset.fields):
                if len(container) and isinstance(container[0], Column):
                    container[0].fields.append(other_fieldset)
                else:
                    container.append(other_fieldset)

        return layout

    @pluginhook
    def get_form_helper(self):
        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        helper.add_layout(self.get_form_layout())

        return helper

    def setup_forms(self):
        helper = self.get_form_helper()
        if helper:
            self.form_obj.helper = helper

    @pluginhook
    def get_media(self):
        return super(ActionFormViewTemplate, self).get_media() + self.form_obj.media + \
               self.vendor('website.page.form.js', 'website.form.css')

    @pluginhook
    def prepare_form(self):
        self.view_form = self.form

    @pluginhook
    def instance_forms(self):
        self.form_obj = self.view_form(**self.get_form_datas())

    def get_redirect_url(self):
        action_return_url = self.request.POST.get('_action_return_url')
        return action_return_url

    def action(self, queryset):
        pass

    def do_action(self, queryset):
        self.prepare_form()
        self.instance_forms()
        self.setup_forms()

        if self.request.POST.get('post') and '_save' in self.request.POST:
            if self.form_obj.is_valid():
                ret = self.action(queryset)
                if ret:
                    if isinstance(ret, str):
                        self.message_user(ret, 'error')
                    elif isinstance(ret, HttpResponse):
                        return ret
                else:
                    self.message_user('操作成功', 'success')
                    return None

        context = self.get_context()
        context.update({
            'title': self.verbose_name or self.__class__.__bases__[1].__name__,
            'form': self.form_obj,
            'queryset': queryset,
            'count': len(queryset),
            "opts": self.opts,
            "app_label": self.app_label,
            'action_checkbox_name': ACTION_CHECKBOX_NAME,
            'action_name': 'act_' + self.__class__.__bases__[1].__name__,
            'return_url': self.request.POST.get('_action_return_url') if '_action_return_url' in self.request.POST else
            self.request.META['HTTP_REFERER'],
            'action_url': self.action_url
        })

        return TemplateResponse(self.request, self.form_template, context)


class BatchDeletionViewTemplate(ActionViewTemplate):
    action_name = "delete_selected"
    verbose_name = '批量删除'  # _('Delete selected %(verbose_name_plural)s')

    delete_confirmation_template = None
    delete_selected_confirmation_template = None

    model_perm = 'delete'
    icon = 'fa fa-times'

    def do_deletes(self, queryset):
        if self.log:
            for obj in queryset:
                self.log_deletion(self.request, obj)
        queryset.delete()

    @pluginhook
    def delete_models(self, queryset):
        '''orm删除对象'''
        n = queryset.count()
        if n:
            self.do_deletes(queryset)
            self.message_user(
                _("Successfully deleted %(count)d %(items)s.") % {"count": n, "items": model_ngettext(self.opts, n)},
                'success')

    @pluginhook
    def do_action(self, queryset):
        # 检查是否有删除权限
        if not self.has_delete_permission():
            raise PermissionDenied

        using = router.db_for_write(self.model)

        # Populate deletable_objects, a data structure of all related objects that
        # will also be deleted.
        deletable_objects, perms_needed, protected = get_deleted_objects(
            queryset, self.opts, self.user, self.website, using)

        # The user has already confirmed the deletion.
        # Do the deletion and return a None to display the change list view again.
        if self.request.POST.get('post'):
            if perms_needed:
                raise PermissionDenied
            self.delete_models(queryset)
            # Return None to display the change list page again.
            return None
        # GET请求 删除确认页面
        if len(queryset) == 1:
            objects_name = force_str(self.opts.verbose_name)
        else:
            objects_name = force_str(self.opts.verbose_name_plural)

        if perms_needed or protected:
            title = _("Cannot delete %(name)s") % {"name": objects_name}
        else:
            title = _("Are you sure?")

        context = self.get_context()
        context.update({
            "title": title,
            "objects_name": objects_name,
            "deletable_objects": [deletable_objects],
            'queryset': queryset,
            "perms_lacking": perms_needed,
            "protected": protected,
            "opts": self.opts,
            "app_label": self.app_label,
            'action_checkbox_name': ACTION_CHECKBOX_NAME,
        })

        return TemplateResponse(self.request, self.delete_selected_confirmation_template or
                                self.get_template_list('views/model_delete_selected_confirm.tpl'), context)

    def log_deletion(self, request, object):
        """
        删除对象日志
        """
        from django.contrib.baseadmin.models import LogEntry, DELETION
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(self.model).pk,
            object_id=object.pk,
            object_repr=force_text(object),
            action_flag=DELETION
        )


class BatchChangeViewTemplate(ActionViewTemplate):
    action_name = "change_selected"
    verbose_name = ugettext_lazy(
        'Batch Change selected %(verbose_name_plural)s')

    batch_change_form_template = None

    model_perm = 'change'

    batch_fields = []

    def change_models(self, queryset, cleaned_data):
        n = queryset.count()

        data = {}
        for f in self.opts.fields:
            if not f.editable or isinstance(f, models.AutoField) \
                    or not f.name in cleaned_data:
                continue
            data[f] = cleaned_data[f.name]

        if n:
            for obj in queryset:
                for f, v in list(data.items()):
                    f.save_form_data(obj, v)
                obj.save()
            self.message_user(_("Successfully change %(count)d %(items)s.") % {
                "count": n, "items": model_ngettext(self.opts, n)
            }, 'success')

    def get_change_form(self, is_post, fields):
        edit_view = self.getmodelviewclass(ModelFormViewTemplate, self.model)

        def formfield_for_dbfield(db_field, **kwargs):
            formfield = edit_view.formfield_for_dbfield(db_field, required=is_post, **kwargs)
            formfield.widget = ChangeFieldWidgetWrapper(formfield.widget)
            return formfield

        defaults = {
            "form": edit_view.form,
            "fields": fields,
            "formfield_callback": formfield_for_dbfield,
        }
        return modelform_factory(self.model, **defaults)

    def do_action(self, queryset):
        if not self.has_change_permission():
            raise PermissionDenied

        change_fields = [f for f in self.request.POST.getlist(BATCH_CHECKBOX_NAME) if f in self.batch_fields]

        if change_fields and self.request.POST.get('post'):
            self.form_obj = self.get_change_form(True, change_fields)(
                data=self.request.POST, files=self.request.FILES)
            if self.form_obj.is_valid():
                self.change_models(queryset, self.form_obj.cleaned_data)
                return None
        else:
            self.form_obj = self.get_change_form(False, self.batch_fields)()

        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        helper.add_layout(Layout(Container(Col('full',
                                               Fieldset("", *list(self.form_obj.fields.keys()),
                                                        css_class="unsort no_title"),
                                               horizontal=True, span=12)
                                           )))
        self.form_obj.helper = helper
        count = len(queryset)
        if count == 1:
            objects_name = force_str(self.opts.verbose_name)
        else:
            objects_name = force_str(self.opts.verbose_name_plural)

        context = self.get_context()
        context.update({
            "title": _("Batch change %s") % objects_name,
            'objects_name': objects_name,
            'form': self.form_obj,
            'queryset': queryset,
            'count': count,
            "opts": self.opts,
            "app_label": self.app_label,
            'action_checkbox_name': ACTION_CHECKBOX_NAME,
        })

        return TemplateResponse(self.request, self.batch_change_form_template or
                                self.get_template_list('receiversviews/batch_change_form.tpl'), context)

    @pluginhook
    def get_media(self):
        media = super(BatchChangeViewTemplate, self).get_media()
        media = media + self.form_obj.media + self.vendor(
            'website.page.form.js', 'website.form.css')
        return media


class ChartsViewTemplate(ListViewTemplate):
    data_charts = {}

    def get_ordering(self):
        if 'order' in self.chart:
            return self.chart['order']
        else:
            return super(ChartsViewTemplate, self).get_ordering()

    def get(self, request, name):
        if name not in self.data_charts:
            return HttpResponseNotFound()

        self.chart = self.data_charts[name]

        self.x_field = self.chart['x-field']
        y_fields = self.chart['y-field']
        self.y_fields = (
            y_fields,) if type(y_fields) not in (list, tuple) else y_fields

        datas = [{"data": [], "label": force_str(label_for_field(
            i, self.model, model_admin=self))} for i in self.y_fields]

        self.make_result_list()

        for obj in self.result_list:
            xf, attrs, value = lookup_field(self.x_field, obj, self)
            for i, yfname in enumerate(self.y_fields):
                yf, yattrs, yv = lookup_field(yfname, obj, self)
                datas[i]["data"].append((value, yv))

        option = {'series': {'lines': {'show': True}, 'points': {'show': False}},
                  'grid': {'hoverable': True, 'clickable': True}}
        try:
            xfield = self.opts.get_field(self.x_field)
            if type(xfield) in (models.DateTimeField, models.DateField, models.TimeField):
                option['xaxis'] = {'mode': "time", 'tickLength': 5}
                if type(xfield) is models.DateField:
                    option['xaxis']['timeformat'] = "%y/%m/%d"
                elif type(xfield) is models.TimeField:
                    option['xaxis']['timeformat'] = "%H:%M:%S"
                else:
                    option['xaxis']['timeformat'] = "%y/%m/%d %H:%M:%S"
        except Exception:
            pass

        option.update(self.chart.get('option', {}))

        content = {'data': datas, 'option': option}
        result = json.dumps(content, cls=JSONEncoder, ensure_ascii=False)

        return HttpResponse(result)


class EditPatchViewTemplateTemplate(ModelFormViewTemplate, ListViewTemplate):
    def init_request(self, object_id, *args, **kwargs):
        self.org_obj = self.get_object(unquote(object_id))

        if not self.has_change_permission(self.org_obj):
            raise PermissionDenied

        if self.org_obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') %
                          {'name': force_str(self.opts.verbose_name), 'key': escape(object_id)})

    def get_new_field_html(self, f):
        result = self.makecell(self.org_obj, f, {'is_display_first':
                                                     False, 'object': self.org_obj})
        return mark_safe(result.text) if result.allow_tags else conditional_escape(result.text)

    def _get_new_field_html(self, field_name):
        try:
            f, attr, value = lookup_field(field_name, self.org_obj, self)
        except (AttributeError, ObjectDoesNotExist):
            return EMPTY_CHANGELIST_VALUE
        else:
            allow_tags = False
            if f is None:
                allow_tags = getattr(attr, 'allow_tags', False)
                boolean = getattr(attr, 'boolean', False)
                if boolean:
                    allow_tags = True
                    text = boolean_icon(value)
                else:
                    text = smart_str(value)
            else:
                if isinstance(f.rel, models.ManyToOneRel):
                    field_val = getattr(self.org_obj, f.name)
                    if field_val is None:
                        text = EMPTY_CHANGELIST_VALUE
                    else:
                        text = field_val
                else:
                    text = display_for_field(value, f)
            return mark_safe(text) if allow_tags else conditional_escape(text)

    @pluginhook
    def get(self, request, object_id):
        model_fields = [f.name for f in self.opts.fields]
        fields = [f for f in request.GET['fields'].split(',') if f in model_fields]
        defaults = {
            "form": forms.ModelForm,
            "fields": fields,
            "formfield_callback": self.formfield_for_dbfield,
        }
        form_class = modelform_factory(self.model, **defaults)
        form = form_class(instance=self.org_obj)

        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        form.helper = helper

        s = '{% load i18n crispy_forms_tags %}<form method="post" action="{{action_url}}" autocomplete="off">{% crispy form %}' + \
            '<button type="submit" class="btn btn-success btn-block btn-sm">{% trans "Apply" %}</button></form>'
        t = template.Template(s)
        c = template.Context({'form': form, 'action_url': self.model_admin_url('patch', self.org_obj.pk)})

        return HttpResponse(t.render(c))

    def do_patch(self):
        self.patch_form.save(commit=True)

    @pluginhook
    @csrf_protect_m
    @dutils.commit_on_success
    def post(self, request, object_id):
        model_fields = [f.name for f in self.opts.fields]
        fields = [f for f in list(request.POST.keys()) if f in model_fields]
        defaults = {
            "form": forms.ModelForm,
            "fields": fields,
            "formfield_callback": self.formfield_for_dbfield,
        }
        form_class = modelform_factory(self.model, **defaults)
        form = form_class(
            instance=self.org_obj, data=request.POST, files=request.FILES)

        result = {}
        if form.is_valid():
            self.patch_form = form
            ret = self.do_patch()
            if ret:
                result['result'] = 'error'
                result['errors'] = [{'errors': [ret]}]
            else:
                result['result'] = 'success'
                result['new_data'] = form.cleaned_data
                result['new_html'] = dict(
                    [(f, self.get_new_field_html(f)) for f in fields])
        else:
            result['result'] = 'error'
            result['errors'] = JsonErrorDict(form.errors, form).as_json()

        return self.render_response(result)


class ResetPasswordSendView(ViewTemplate):
    need_login_permission = False

    password_reset_form = PasswordResetForm
    password_reset_template = 'website/auth/password_reset/form.tpl'
    password_reset_done_template = 'website/auth/password_reset/done.tpl'
    password_reset_token_generator = default_token_generator

    password_reset_from_email = None
    password_reset_email_template = 'website/auth/password_reset/email.tpl'
    password_reset_subject_template = 'website/auth/password_reset/email_subject.tpl'

    def get(self, request, *args, **kwargs):
        context = super(ResetPasswordSendView, self).get_context()
        context['form'] = kwargs.get('form', self.password_reset_form())

        return TemplateResponse(request, self.password_reset_template, context)

    @csrf_protect_m
    def post(self, request, *args, **kwargs):
        form = self.password_reset_form(request.POST)

        if form.is_valid():
            opts = {
                'use_https': request.is_secure(),
                'token_generator': self.password_reset_token_generator,
                'email_template_name': self.password_reset_email_template,
                'html_email_template_name': self.password_reset_email_template,
                'request': request,
                'domain_override': request.get_host()
            }

            if self.password_reset_from_email:
                opts['from_email'] = self.password_reset_from_email
            if self.password_reset_subject_template:
                opts['subject_template_name'] = self.password_reset_subject_template

            form.save(**opts)
            context = super(ResetPasswordSendView, self).get_context()
            return TemplateResponse(request, self.password_reset_done_template, context)
        else:
            return self.get(request, form=form)


class ResetPasswordComfirmView(ViewTemplate):
    need_login_permission = False

    password_reset_set_form = SetPasswordForm
    password_reset_confirm_template = 'website/auth/password_reset/confirm.tpl'
    password_reset_token_generator = default_token_generator

    def do_view(self, request, uidb36, token, *args, **kwargs):
        context = super(ResetPasswordComfirmView, self).get_context()
        return password_reset_confirm(request, uidb36, token,
                                      template_name=self.password_reset_confirm_template,
                                      token_generator=self.password_reset_token_generator,
                                      set_password_form=self.password_reset_set_form,
                                      post_reset_redirect=self.get_site_url('xadmin_password_reset_complete'),
                                      current_app=self.website.module_name, extra_context=context)

    def get(self, request, uidb36, token, *args, **kwargs):
        return self.do_view(request, uidb36, token)

    def post(self, request, uidb36, token, *args, **kwargs):
        return self.do_view(request, uidb36, token)

    def get_media(self):
        return super(ResetPasswordComfirmView, self).get_media() + \
               self.vendor('website.page.form.js', 'website.form.css')


class ResetPasswordCompleteView(ViewTemplate):
    need_login_permission = False

    password_reset_complete_template = 'website/auth/password_reset/complete.tpl'

    def get(self, request, *args, **kwargs):
        context = super(ResetPasswordCompleteView, self).get_context()
        context['login_url'] = self.get_site_url('index')

        return TemplateResponse(request, self.password_reset_complete_template, context)


class LoginView(ViewTemplate):
    title = _("登陆")
    login_form = None
    login_template = None

    @pluginhook
    def update_params(self, defaults):
        pass

    @never_cache
    def get(self, request, *args, **kwargs):
        context = self.get_context()
        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        context.update({
            'title': self.title,
            'helper': helper,
            'module_path': request.get_full_path(),
            REDIRECT_FIELD_NAME: request.get_full_path(),
            'base_template': self.website.style_adminlte and 'website/adminlte.tpl' or self.base_template,
            'adminlte': self.website.style_adminlte
        })
        defaults = {
            'extra_context': context,
            # 'current_app': self.website.module_name,
            'authentication_form': self.login_form or AdminAuthenticationForm,
            'template_name': self.login_template or 'website/auth/login.tpl',
        }
        self.update_params(defaults)
        return login(request, **defaults)

    @never_cache
    def post(self, request, *args, **kwargs):
        return self.get(request)


class LogoutView(ViewTemplate):
    logout_template = None
    need_login_permission = False

    @pluginhook
    def update_params(self, defaults):
        pass

    @never_cache
    def get(self, request, *args, **kwargs):
        context = self.get_context()
        defaults = {
            'extra_context': context,
            # 'current_app': self.website.module_name,
            'template_name': self.logout_template or 'access/logged_out.tpl',
        }
        if self.logout_template is not None:
            defaults['template_name'] = self.logout_template

        self.update_params(defaults)
        logout(request, **defaults)
        return HttpResponseRedirect(self.get_param('_redirect') or self.get_site_url('index'))

    @never_cache
    def post(self, request, *args, **kwargs):
        return self.get(request)


class UserSettingView(ViewTemplate):
    @never_cache
    def post(self, request):
        key = request.POST['key']
        val = request.POST['value']
        us, created = UserSetting.objects.get_or_create(
            user=self.user, key=key)
        us.value = val
        us.save()
        return HttpResponse('')


class GroupAddUsersView(ActionFormViewTemplate):
    verbose_name = '批量添加成员'
    app_label = 'website'

    def prepare_form(self):
        class GroupAddUsersForm(forms.Form):
            users = forms.CharField(label='选择用户',
                                    widget=website.views.widgets.ManyToManyPopupWidget(self, User, 'id'))

        self.view_form = GroupAddUsersForm

    def action(self, queryset):
        m_data = self.form_obj.cleaned_data
        users = m_data.get('users').split(',')
        users = list(map(int, users))

        for group in queryset:
            for user in users:
                user_obj = User.objects.get(id=user)
                user_obj.groups.add(group)


class ChangePasswordView(ModelViewTemplate):
    '''
    管理员修改用户密码
    '''
    menu_show = False

    model = User
    change_password_form = AdminPasswordChangeForm
    change_user_password_template = None

    @csrf_protect_m
    def get(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        self.obj = self.get_object(unquote(object_id))
        self.form = self.change_password_form(self.obj)

        return self.get_response()

    def get_media(self):
        media = super(ChangePasswordView, self).get_media()
        media = media + self.vendor('website.form.css', 'website.page.form.js') + self.form.media
        return media

    def get_context(self):
        context = super(ChangePasswordView, self).get_context()
        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        self.form.helper = helper
        context.update({
            'title': _('Change password: %s') % escape(str(self.obj)),
            'form': self.form,
            'has_delete_permission': False,
            'has_change_permission': True,
            'has_view_permission': True,
            'original': self.obj,
        })
        return context

    def get_response(self):
        return TemplateResponse(self.request, [
            self.change_user_password_template or
            'website/auth/user/change_password.tpl'
        ], self.get_context())

    @method_decorator(sensitive_post_parameters())
    @csrf_protect_m
    def post(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        self.obj = self.get_object(unquote(object_id))
        self.form = self.change_password_form(self.obj, request.POST)

        if self.form.is_valid():
            self.form.save()
            self.message_user(_('Password changed successfully.'), 'success')
            return HttpResponseRedirect(self.model_admin_url('change', self.obj.pk))
        else:
            return self.get_response()


class ChangeAccountPasswordView(ChangePasswordView):
    '''
    用户修改自己密码
    '''
    menu_show = False
    change_password_form = PasswordChangeForm

    @csrf_protect_m
    def get(self, request):
        self.obj = self.user
        self.form = self.change_password_form(self.obj)

        return self.get_response()

    def get_context(self):
        context = super(ChangeAccountPasswordView, self).get_context()
        context.update({
            'title': _('Change password'),
            'account_view': True,
        })
        return context

    @method_decorator(sensitive_post_parameters())
    @csrf_protect_m
    def post(self, request):
        self.obj = self.user
        self.form = self.change_password_form(self.obj, request.POST)

        if self.form.is_valid():
            self.form.save()
            self.message_user(_('Password changed successfully.'), 'success')
            return HttpResponseRedirect(self.get_site_url('index'))
        else:
            return self.get_response()


class ViewmarkView(ModelViewTemplate):
    @csrf_protect_m
    @dutils.commit_on_success
    def post(self, request):
        model_info = (self.opts.app_label, self.opts.model_name)
        url_name = '%s:%s_%s_changelist' % (self.website.namespace, *model_info)
        viewmark = Viewmark(
            content_type=ContentType.objects.get_for_model(self.model),
            title=request.POST[
                'title'], user=self.user, query=request.POST.get('query', ''),
            is_share=request.POST.get('is_share', 0), url_name=url_name)
        viewmark.save()
        content = {'title': viewmark.title, 'url': viewmark.url}
        return HttpResponseRedirect(viewmark.url)


class UserViewConfig(ViewConfigMixin):
    change_user_password_template = None
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
    list_filter = ('is_staff', 'is_superuser', 'is_active')
    filter_default_list = ['is_staff', 'is_superuser']
    filter_list_position = 'top'
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)
    style_fields = {
        'groups': 'm2m_transfer',
        'user_permissions': 'm2m_transfer'
    }
    menu_icon = 'fa fa-user'
    relfield_style = 'fk-ajax'
    menu_group = '配置 角色'

    def get_field_attrs(self, db_field, **kwargs):
        attrs = super(UserViewConfig, self).get_field_attrs(db_field, **kwargs)
        if db_field.name == 'user_permissions':
            attrs['form_class'] = PermissionModelMultipleChoiceField
        return attrs

    def get_model_form(self, **kwargs):
        if self.org_obj is None:
            self.form = UserCreationForm
        else:
            self.form = UserChangeForm
        return super(UserViewConfig, self).get_model_form(**kwargs)

    def get_form_layout(self):
        if self.org_obj:
            self.form_layout = (
                Main(
                    Fieldset('',
                             'username', 'password',
                             css_class='unsort no_title'
                             ),
                    Fieldset(_('Personal info'),
                             Row('first_name', 'last_name'),
                             'email'
                             ),
                    Fieldset(_('Permissions'),
                             'groups', 'user_permissions'
                             ),
                    Fieldset(_('Important dates'),
                             'last_login', 'date_joined'
                             ),
                ),
                Side(
                    Fieldset(_('Status'),
                             'is_active', 'is_staff', 'is_superuser',
                             ),
                )
            )
        return super(UserViewConfig, self).get_form_layout()

    @pluginhook
    def get_model_form(self, **kwargs):
        if not self.request.user.is_superuser:
            self.exclude = self.exclude and self.exclude + ['is_superuser'] or ['is_superuser']

        return super(UserViewConfig, self).get_model_form(**kwargs)

    @pluginhook
    def queryset(self):
        qs = super(UserViewConfig, self).queryset()
        if self.user.is_superuser:
            return qs
        else:
            return qs.filter(is_superuser=False)


class GroupViewConfig(ViewConfigMixin):
    search_fields = ('name',)
    ordering = ('name',)
    style_fields = {'permissions': 'm2m_transfer'}
    menu_icon = 'fa fa-group'
    menu_group = '配置 角色'
    menu_group_icon = 'fa fa-cog'

    actions = [GroupAddUsersView]

    def get_field_attrs(self, db_field, **kwargs):
        attrs = super(GroupViewConfig, self).get_field_attrs(db_field, **kwargs)
        if db_field.name == 'permissions':
            attrs['form_class'] = PermissionModelMultipleChoiceField
        return attrs


class PermissionViewConfig(ViewConfigMixin):
    def show_name(self, p):
        def get_permission_name(p):
            action = p.codename.split('_')[0]
            if action in ACTION_NAME:
                return ACTION_NAME[action] % str(p.content_type)
            else:
                return p.name

        return get_permission_name(p)

    show_name.verbose_name = _('操作')
    show_name.is_column = True

    menu_icon = 'fa fa-lock'
    list_display = ['content_type', 'show_name', 'codename']
    menu_group = '配置 角色'

    list_filter = ['name', 'codename']
    # filter_default_list = ['content_type']
    # filter_list_position = 'top'


class ViewmarkViewConfig(ViewConfigMixin):
    menu_icon = 'fa fa-book'
    list_display = ('title', 'user', 'url_name', 'query')
    list_display_links = ('title',)
    user_fields = ['user']
    menu_group = '配置 个人中心'

    hide_menu = False

    def queryset(self):
        if self.user.is_superuser:
            return Viewmark.objects.all()
        return Viewmark.objects.filter(Q(user=self.user) | Q(is_share=True))

    def get_list_display(self):
        list_display = super(ViewmarkViewConfig, self).get_list_display()
        if not self.user.is_superuser:
            list_display.remove('user')
        return list_display

    def has_change_permission(self, obj=None):
        if not obj or self.user.is_superuser:
            return True
        else:
            return obj.user == self.user


class UserSettingViewConfig(ViewConfigMixin):
    menu_icon = 'fa fa-cog'
    hide_menu = False
    menu_group = '配置 个人中心'


class UserComponentViewConfig(ViewConfigMixin):
    menu_icon = 'fa fa-dashboard'
    list_display = ('widget_type', 'page_id', 'user')
    list_filter = ['user', 'widget_type', 'page_id']
    list_display_links = ('widget_type',)
    user_fields = ['user']
    # hide_menu = True
    menu_group = '配置 个人中心'
    menu_group_icon = 'fa fa-address-card'
    hide_menu = False

    wizard_form_list = (
        ('组件类型', ('page_id', 'widget_type')),
        ('组件参数', {'callback': "get_widget_params_form", 'convert': "convert_widget_params"})
    )

    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == 'widget_type':
            widgets = componentmanager.get_widgets(self.request.GET.get('page_id', ''))
            form_widget = WidgetTypeSelect(widgets)
            return forms.ChoiceField(choices=[(w.widget_type, w.description) for w in widgets],
                                     widget=form_widget, label=_('Widget Type'))
        if 'page_id' in self.request.GET and db_field.name == 'page_id':
            kwargs['widget'] = forms.HiddenInput
        field = super(
            UserComponentViewConfig, self).formfield_for_dbfield(db_field, **kwargs)
        return field

    def get_widget_params_form(self, wizard):
        data = wizard.get_cleaned_data_for_step(wizard.steps.first)
        widget_type = data['widget_type']
        widget = componentmanager.get(widget_type)
        fields = copy.deepcopy(widget.base_fields)
        if 'id' in fields:
            del fields['id']
        return DeclarativeFieldsMetaclass("WidgetParamsForm", (forms.Form,), fields)

    def convert_widget_params(self, wizard, cleaned_data, form):
        widget = UserComponent()
        value = dict([(f.name, f.value()) for f in form])
        widget.set_value(value)
        cleaned_data['value'] = widget.value
        cleaned_data['user'] = self.user

    def get_list_display(self):
        list_display = super(UserComponentViewConfig, self).get_list_display()
        if not self.user.is_superuser:
            list_display.remove('user')
        return list_display

    def queryset(self):
        if self.user.is_superuser:
            return super(UserComponentViewConfig, self).queryset()
        return UserComponent.objects.filter(user=self.user)

    def update_dashboard(self, obj):
        try:
            portal_pos = UserSetting.objects.get(
                user=obj.user, key="dashboard:%s:pos" % obj.page_id)
        except UserSetting.DoesNotExist:
            return
        pos = [[w for w in col.split(',') if w != str(
            obj.id)] for col in portal_pos.value.split('|')]
        portal_pos.value = '|'.join([','.join(col) for col in pos])
        portal_pos.save()

    def delete_model(self):
        self.update_dashboard(self.obj)
        super(UserComponentViewConfig, self).delete_model()

    def delete_models(self, queryset):
        for obj in queryset:
            self.update_dashboard(obj)
        super(UserComponentViewConfig, self).delete_models(queryset)


class ContentTypeViewConfig(ViewConfigMixin):
    menu_group = '配置 系统'


class SessionViewConfig(ViewConfigMixin):
    menu_group = '配置 系统'
