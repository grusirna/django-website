from functools import update_wrapper

import website.views.configs
from django.contrib.auth.models import Group, Permission
from website.views.utils import User
from website.views.views import IFrameViewTemplate, LoginView, LogoutView, UserSettingView, \
    CreateViewTemplate, DeleteView, UpdateViewTemplate, ModelDashboardView, ModelViewTemplate, \
    ChangePasswordView, ChangeAccountPasswordView, ViewmarkView, ChartsViewTemplate, EditPatchViewTemplateTemplate, \
    LayoutViewTemplate, ResetPasswordSendView, ResetPasswordComfirmView, ResetPasswordCompleteView, ViewTemplate, \
    UploadView, UploadDrogImgView, UserViewConfig, GroupViewConfig, PermissionViewConfig, ViewmarkViewConfig, \
    UserSettingViewConfig, \
    UserComponentViewConfig, ContentTypeViewConfig, SessionViewConfig
from website.models import UserComponent, UserSetting, ContentType
from django.db.models.base import ModelBase, Model
from django.urls import re_path
from django.urls.conf import path, include
from django.views.decorators.cache import never_cache
import logging
from website.views.plugins import *
from website.views.views import ModelFormViewTemplate, DetailView, ListViewTemplate
from website.views.views import DashboardViewTemplate
import functools
from website.views.views import ViewTemplate
from website.views.views import ListViewTemplate
from django.contrib.sessions.models import Session
from functools import lru_cache
from django.utils.functional import cached_property

logger = logging.getLogger('website')


class AlreadyRegistered(Exception):
    """
    如果一个 model 已经在 Website 注册过，当尝试再次注册时会抛出这个异常。
    """
    pass


class TypeErrorRegistered(Exception):
    """
    注册到site时类型错误
    """
    pass


class NotRegistered(Exception):
    """
    当一个model并未在 Website 注册，当调用 Website.unregister 想要取消该model的注册就会抛出该异常。
    """
    pass


#
# class AdminType(type):
#
#     def __init__(cls, name, bases, attrs):
#         cls.__name__ =
#         admin_class = type(
#             str("%s__%s__Admin" % (model._meta.app_label, model._meta.model_name)),
#             (base_class,), attrs or {})
#
#
# class AdminClass(metaclass=AdminType):
#     def __init__(self, model, view):
#         pass
""" iknow metaclass
@first __new__ 元类自身产生
@secend __init__ 元类初始化类
@third __call__ 对象产生，也就是类实例化时第一入口，其次才是类__init__
"""


class ViewMeta(type):
    def __new__(mcs, name, bases, website, rear, front=None, **opts):
        plugins = mcs.getpluginclasses(mcs, website, rear, front)
        return type(name, bases, {'pluginclasses': plugins, 'website': website}, **opts)

    def getpluginclasses(mcs, website, rear, *front):
        l = []
        m = [a for a in front if a]
        for a in rear.mro():
            if a == ViewTemplate or issubclass(a, ViewTemplate):
                b = []
                c = website.viewconfigs.get(a)
                if c:
                    b.append(c)
                b.extend(m)
                d = website.viewplugins.get(a, [])
                l.extend(list(map(mcs.createpluginclasses(mcs, b), d)) if b else d)
        return l

    def createpluginclasses(mcs, views):

        def createclass(plugin):
            if views:
                attrs = {}
                bases = [plugin]
                for a in views:
                    attrs.update(mcs.getsameattrs(mcs, a, plugin))
                    meta_class = getattr(a, plugin.__name__,
                                         getattr(a, plugin.__name__.replace('ViewPlugin', ''), None))
                    if meta_class:
                        bases.insert(0, meta_class)
                if attrs:
                    plugin = type(
                        '%s%s' % ('__'.join([i.__name__ for i in views]), plugin.__name__),
                        tuple(bases), attrs)
            return plugin

        return createclass

    def getsameattrs(mcs, view, plugin):
        return dict([(name, getattr(view, name)) for name in dir(view)
                     if name[0] != '_' and not callable(getattr(view, name)) and hasattr(plugin, name)])


from website.tools.types import tree


class WebSite:

    def __init__(self, namespace, ismainsite=True):
        self.ismainsite = ismainsite
        self.namespace = namespace
        self.module_name = self.namespace

        self.modules = SortedDict()
        self.navmenus = tree()
        # @1 先注册
        self.modelconfigs = {}
        self.viewconfigs = {}
        self.viewplugins = {}
        # @2 再创建
        self.modelviewtpls = []
        self.urlviewtpls = []
        # @3 最后合成
        self.viewclasses = {}

        self._check_dependencies()
        self.menu_index = 0

        self.iframe_view = None
        self.show_default_index = True
        self.menu_loaded = False
        self.style_menu = 'inspinia'  # default、accordion
        self.style_adminlte = True
        self.style_fixhead = False
        self.style_footer = ''
        self.style_title = ''
        self.login_view = None
        self.style_theme = 'website/adminlte'  # 'bootstrap3' inspinia

    @property
    def urls(self):
        self.init_res()

        def decor(view, cacheable=False):
            def wrapper(*args, **kwargs):
                return self.view_perm_check_decor(view, cacheable)(*args, **kwargs)

            return update_wrapper(wrapper, view)

        urlpatterns = [
            path('jsi18n/', decor(self.i18n_javascript, cacheable=True), name='jsi18n')
        ]
        urlpatterns += [re_path(a, decor(
            self.createviewclass(b).as_view() if type(b) is type and issubclass(b, ViewTemplate) else include(b)),
                                name=c) for a, b, c in self.urlviewtpls]

        for a, b in self.modelconfigs.items():
            c = [re_path(d, decor(self.createviewclass(e, b).as_view()),
                         name=f % (a._meta.app_label, a._meta.model_name)) for d, e, f in self.modelviewtpls]
            urlpatterns += [re_path(r'^%s/%s/' % (a._meta.app_label, a._meta.model_name), include(c))]

        return (urlpatterns, self.module_name, self.namespace)

    def register(self, v_or_m_or_p=None, name=None, update=True):
        def clsobj(cls):
            if v_or_m_or_p and cls:
                if issubclass(cls, ViewPlugin):
                    self.add_plugin(cls, v_or_m_or_p)
                elif name and issubclass(cls, ViewTemplate):
                    self.add_urlview(v_or_m_or_p, cls, name, update)
                elif issubclass(v_or_m_or_p, Model) or issubclass(v_or_m_or_p, ViewTemplate):
                    self.register_modelorview(v_or_m_or_p, cls)
                    if issubclass(v_or_m_or_p, Model):
                        cls.model = v_or_m_or_p
            else:
                namespace = cls.__name__
                self.add_urlview(r'^page/%s/$' % namespace.lower(), cls, namespace)
            update_wrapper(clsobj, cls)
            return cls

        return clsobj

    def mainsite(self):
        self.register_modelorview(ContentType, ContentTypeViewConfig)
        self.register_modelorview(Group, GroupViewConfig)
        self.register_modelorview(User, UserViewConfig)
        self.register_modelorview(Session, SessionViewConfig)
        self.register_modelorview(Permission, PermissionViewConfig)

    def init_res(self):
        if self.ismainsite:
            self.mainsite()
        setattr(settings, 'CRISPY_TEMPLATE_PACK', 'bootstrap3')
        setattr(settings, 'CRISPY_CLASS_CONVERTERS', {
            "textinput": "textinput textInput form-control",
            "fileinput": "fileinput fileUpload form-control",
            "passwordinput": "textinput textInput form-control",
        })
        self.register_modelorview(Viewmark, ViewmarkViewConfig)
        self.register_modelorview(UserSetting, UserSettingViewConfig)
        self.register_modelorview(UserComponent, UserComponentViewConfig)
        self.add_urlview(r'^$', DashboardViewTemplate, name='index')
        self.add_urlview(r'^main', IFrameViewTemplate, name='main')
        self.add_urlview(r'^login/$', LoginView, name='login')
        self.add_urlview(r'^logout/$', LogoutView, name='logout')
        self.add_urlview(r'^settings/user', UserSettingView, name='user_settings')
        self.add_urlview(r'^auth/user/(.+)/update/password/$',
                         ChangePasswordView, name='user_change_password')
        self.add_urlview(r'^account/password/$', ChangeAccountPasswordView,
                         name='account_password')
        self.add_urlview(r'^website/password_reset/$', ResetPasswordSendView,
                         name='base_password_reset')
        self.add_urlview(
            r'^website/password_reset/(?P<uidb36>[0-9A-Za-z]{1,13})-(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
            ResetPasswordComfirmView, name='base_password_reset_confirm')

        self.add_urlview(r'^website/password_reset/complete/$', ResetPasswordCompleteView,
                         name='base_password_reset_complete')
        self.add_urlview(r'^ckupload/$', UploadView, name='ckupload')
        self.add_urlview(r'^ckupdrogload/$', UploadDrogImgView, name='ckupdrogupload')
        self.set_login_view(LoginView)
        self.add_modelview(r'^$', ListViewTemplate, name='%s_%s_changelist')
        self.add_modelview(r'^add/$', CreateViewTemplate, name='%s_%s_add')
        self.add_modelview(r'^(.+)/delete/$', DeleteView, name='%s_%s_delete')
        self.add_modelview(r'^(.+)/update/$', UpdateViewTemplate, name='%s_%s_change')
        self.add_modelview(r'^(.+)/detail/$', DetailView, name='%s_%s_detail')
        self.add_modelview(r'^(.+)/dashboard/$', ModelDashboardView, name='%s_%s_dashboard')
        self.add_modelview(r'^viewmark/$', ViewmarkView, name='%s_%s_viewmark')
        self.add_modelview(r'^chart/(.+)/$', ChartsViewTemplate, name='%s_%s_chart')
        self.add_modelview(r'^(.+)/patch/$', EditPatchViewTemplateTemplate, name='%s_%s_patch')
        # <editor-fold desc="List View">
        self.add_plugin(ActionPlugin, ListViewTemplate)
        self.add_plugin(AjaxListPlugin, ListViewTemplate)
        self.add_plugin(AggregationPlugin, ListViewTemplate)
        # self.add_plugin(ViewmarkPlugin, ListViewTemplate)
        self.add_plugin(ChartsPlugin, ListViewTemplate)
        self.add_plugin(DetailsPlugin, ListViewTemplate)
        self.add_plugin(EditablePlugin, ListViewTemplate)
        self.add_plugin(ExportMenuPlugin, ListViewTemplate)
        self.add_plugin(ExportPlugin, ListViewTemplate)
        self.add_plugin(FilterPlugin, ListViewTemplate)
        self.add_plugin(QuickFilterPlugin, ListViewTemplate)
        self.add_plugin(ModelListPlugin, ListViewTemplate)
        self.add_plugin(GridLayoutPlugin, ListViewTemplate)
        self.add_plugin(RefreshPlugin, ListViewTemplate)
        self.add_plugin(RelateMenuPlugin, ListViewTemplate)
        self.add_plugin(ListRelateDisplayPlugin, ListViewTemplate)
        self.add_plugin(SortablePlugin, ListViewTemplate)

        # </editor-fold>
        # <editor-fold desc="Detail View">
        self.add_plugin(AjaxDetailPlugin, DetailView)
        self.add_plugin(ModelDetailPlugin, DetailView)
        # self.add_plugin(DetailInlineFormsetPlugin, DetailView)
        self.add_plugin(PortalModelDetailPlugin, DetailView)
        self.add_plugin(WYSIHtml5Plugin, DetailView)

        # </editor-fold>
        # <editor-fold desc="Form View">
        self.add_plugin(AjaxFormPlugin, ModelFormViewTemplate)
        self.add_plugin(UserFieldPlugin, ModelFormViewTemplate)
        self.add_plugin(ModelDetailPlugin, ModelFormViewTemplate)
        self.add_plugin(InlineFormsetPlugin, ModelFormViewTemplate)
        self.add_plugin(M2MSelectPlugin, ModelFormViewTemplate)
        self.add_plugin(ModelFormPlugin, ModelFormViewTemplate)
        self.add_plugin(QuickFormPlugin, ModelFormViewTemplate)
        self.add_plugin(QuickAddBtnPlugin, ModelFormViewTemplate)
        self.add_plugin(RelateFieldPlugin, ModelFormViewTemplate)
        self.add_plugin(WYSIHtml5Plugin, ModelFormViewTemplate)
        self.add_plugin(WizardFormPlugin, ModelFormViewTemplate)
        self.add_plugin(M2MTreePlugin, ModelFormViewTemplate)

        # </editor-fold>

        # <editor-fold desc="Edit View">
        # self.add_plugin(ActionPlugin, UpdateViewTemplate)
        self.add_plugin(EditRelateDisplayPlugin, UpdateViewTemplate)
        self.add_plugin(EditRelateDisplayPlugin, CreateViewTemplate)

        # </editor-fold>

        # <editor-fold desc="Delete View">
        self.add_plugin(DeleteRelateDisplayPlugin, DeleteView)
        # </editor-fold>

        self.add_plugin(ModelPermissionPlugin, ModelViewTemplate)

        # <editor-fold desc="UI Layout View">
        self.add_plugin(ThemePlugin, ViewTemplate)
        self.add_plugin(MobilePlugin, LayoutViewTemplate)
        # self.add_plugin(TopNavPlugin, LayoutViewTemplate)
        # if settings.LANGUAGES and 'django.middleware.locale.LocaleMiddleware' in settings.MIDDLEWARE:
        #     print(settings.LANGUAGES)
        #     self.add_plugin(SetLangNavPlugin, LayoutViewTemplate)
        #     self.add_uiview(r'^i18n/', lambda self: 'django.conf.urls.i18n', 'i18n')

        # </editor-fold>

    # <editor-fold desc="add">
    def add_modelview(self, reg, view, name):

        if issubclass(view, ViewTemplate):
            self.modelviewtpls.append((reg, view, name))
        else:
            raise ImproperlyConfigured(
                'The registered view class %s isn\'t subclass of %s' % (
                    view.__name__, ViewTemplate.__name__))

    def add_urlview(self, path, view, name, update=False):
        if update == False:
            self.urlviewtpls.append((path, view, name))
        else:
            self.urlviewtpls.insert(0, (path, view, name))

    def add_moduleview(self, module_index_view):
        app_label = module_index_view.app_label
        name = '%s_%s' % (app_label, module_index_view.__name__)
        logger.debug(self.modules)
        self.modules[app_label].index_url_name = name
        self.add_urlview(r'^index/%s/$' % app_label, module_index_view, name)

    # </editor-fold>

    # <editor-fold desc="register">

    # @1
    def register_modelorview(self, modelorconfig, config=object, **attrs):

        if isinstance(modelorconfig, ModelBase) or issubclass(modelorconfig, ViewTemplate):
            modelorconfig = [modelorconfig]

            for a in modelorconfig:
                if isinstance(a, ModelBase):  # 当为模型Model时
                    model = a
                    if model._meta.abstract:
                        raise ImproperlyConfigured(
                            'The model %s is abstract, so it cannot be registered with website.' % a.__name__)

                    if model in self.modelconfigs:
                        raise AlreadyRegistered('The model %s is already registered' % model.__name__)

                    if attrs:
                        # For reasons I don't quite understand, without a __module__  the created class appears to "live" in the wrong place, which causes issues later on.
                        attrs['__module__'] = __name__

                    new_class = type(str("%s%sView" % (model._meta.app_label, model._meta.model_name)),
                                     (config,), attrs or {})
                    new_class.model = model
                    if not hasattr(new_class, "order"):
                        new_class.order = self.menu_index
                        self.menu_index += 1
                    self.modelconfigs[model] = new_class
                else:
                    orgview = a
                    if config in self.viewconfigs:
                        raise AlreadyRegistered('The view_class %s is already registered' % config.__name__)
                    if attrs:
                        attrs['__module__'] = __name__
                    name = "%sConfig" % orgview.__name__
                    new_class = type(name, (config,), attrs)
                    self.viewconfigs[orgview] = new_class
        else:
            raise TypeErrorRegistered('注册的%s即不是model也不是config' % modelorconfig.__name__)

    def unregister_modelorview(self, m_v):
        if isinstance(m_v, ModelBase):
            if m_v not in self.modelconfigs:
                raise NotRegistered(
                    'The model %s is not registered' % m_v.__name__)
            del self.modelconfigs[m_v]
        else:
            if m_v not in self.viewconfigs:
                raise NotRegistered('The view_class %s is not registered' % m_v.__name__)
            del self.viewconfigs[m_v]

    # </editor-fold>

    # @3
    def createviewclass(self, rear, front=None, **opts):
        l = [front] if front else []
        for a in rear.mro():
            m = self.viewconfigs.get(a)
            if m:
                l.append(m)
            l.append(a)
        n = ''.join([i.__name__ for i in l])
        if n not in self.viewclasses:
            self.viewclasses[n] = ViewMeta(n, tuple(l), self, rear, front, **opts)
        return self.viewclasses[n]

    # <editor-fold desc="plugin ">

    def add_plugin(self, plugin_class, view):
        from website.views.plugins import ViewPlugin
        if issubclass(plugin_class, ViewPlugin):
            self.viewplugins.setdefault(view, []).append(plugin_class)
        else:
            raise ImproperlyConfigured(
                'The registered plugin class %s isn\'t subclass of %s' % (
                    plugin_class.__name__, ViewPlugin.__name__))

            #    def register_settings(self, name, admin_class):
            #        self._registry_settings[name.lower()] = admin_class

    def _check_dependencies(self):
        """
        检查运行需要的包是否已经正确安装

        默认情况下会检查 *ContentType* 模块是否已经正确安装
        """
        from django.contrib.contenttypes.models import ContentType

        if not ContentType._meta.installed:
            raise ImproperlyConfigured("Put 'django.contrib.contenttypes' in "
                                       "your INSTALLED_MODULES setting in order to use the website application.")

    # </editor-fold>

    # <editor-fold desc="util">
    def url_for(self, name, *args, **kwargs):
        return reverse('%s:%s' % (self.namespace, name), current_app=self.namespace)

    def get_model_url(self, model, name, *args, **kwargs):
        """
        路径工具函数
        通过 model, name 取得 url，会自动拼成 urlname，并会加上 Website.module_name 的 url namespace
        """
        return reverse(
            '%s:%s_%s_%s' % (self.module_name, model._meta.app_label,
                             model._meta.model_name, name),
            args=args, kwargs=kwargs, current_app=self.namespace)

    def i18n_javascript(self, request):
        from django.views.i18n import JavaScriptCatalog
        return JavaScriptCatalog.as_view(packages=['website'])(request)

    # </editor-fold>

    # <editor-fold desc="perm">
    def set_login_view(self, login_view):
        self.login_view = login_view

    def has_permission(self, request):
        """
        如果返回为 ``True`` 则说明 ``request.user`` 至少能够访问当前xadmin网站。否则无法访问xadmin的任何页面。
        """
        return request.user.is_active and request.user.is_staff

    def view_perm_check_decor(self, view, cacheable=False):

        def inner(request, *args, **kwargs):
            if not self.has_permission(request) and getattr(view, 'need_login_permission', True):
                _login_view = getattr(view, 'login_view', self.login_view) or self.login_view
                return self.createviewclass(_login_view).as_view()(request, *args, **kwargs)
            return view(request, *args, **kwargs)

        if not cacheable:
            inner = never_cache(inner)
        return update_wrapper(inner, view)

    def get_model_perm(self, model, name):
        return '%s.%s_%s' % (model._meta.app_label, name, model._meta.model_name)

    # </editor-fold>

    def menugroup(self, view, menu):
        last = self.navmenus[0]
        if view.menu_group:
            group = view.menu_group.split()  # '配置 角色 权限' -> ['配置', '角色', '权限']
            for i, t in enumerate(group):
                finded = False
                for b in self.navmenus[i]['branch']:
                    if b['data']['title'] == t:
                        last = b
                        finded = True
                        break
                if not finded:
                    if type(self.navmenus[i]['branch']) != list:
                        self.navmenus[i]['branch'] = []
                    self.navmenus[i]['branch'].append(
                        {'data': {'title': t, 'icon': '', 'url': '#'}, 'branch': [], 'leaf': [],
                         'up': group[i - 1] if i != 0 else ''}
                    )
                    last = self.navmenus[i]['branch'][-1]
        last['leaf'].append(menu)

    @cached_property
    def menus(self):
        self.navmenus[0] = {'data': {}, 'branch': [], 'leaf': []}
        for model, view in self.modelconfigs.items():
            if view.menu_show:
                leaf = {
                    'title': view.menu_name or str(capfirst(model._meta.verbose_name_plural)),
                    'url': self.get_model_url(model, "changelist"),
                    'icon': view.menu_icon,
                    'perm': self.get_model_perm(model, 'view'),
                    'order': view.order,
                }
                self.menugroup(view, leaf)
        for a, view, c in self.urlviewtpls:
            if hasattr(view, 'menu_show') and view.menu_show:
                leaf = {
                    'title': view.menu_name or c,
                    'url': self.url_for(c),
                    'icon': view.menu_icon,
                    'perm': view.perm,
                    'order': view.order,
                }
                self.menugroup(view, leaf)
        return self.navmenus

    def get_module_menu(self, app_label):
        return self.menus[app_label]

    def get_select_menu(self, select_app):
        ret = []
        for app_label, mod in list(self.modules.items()):
            if hasattr(mod, 'menu_name'):
                m_first_url = None
                if hasattr(mod, 'index_url_name'):
                    m_first_url = self.url_for(mod.index_url_name)
                else:
                    module_menu = self.menus[app_label]
                    if hasattr(mod, 'menus'):
                        m_groups = mod.menus
                        for e in m_groups:
                            m_menus = module_menu[e[0]]['menus']
                            if len(m_menus) > 0:
                                m_first_url = m_menus[0]['url']
                                break
                    if not m_first_url:
                        d_menus = module_menu['default_group']['menus']
                        if len(d_menus) > 0:
                            m_first_url = d_menus[0]['url']
                        else:
                            m_first_url = '#'

                ret.append({
                    'app_label': app_label,
                    'title': getattr(mod, 'menu_name', str(capfirst(app_label))),
                    'url': m_first_url,
                    'icon': '',
                    'selected': app_label == select_app
                })
                mod.index_url = m_first_url
        return ret

    # </editor-fold>


""" iknow 代码命名时面向的大致群体
开发者：例如util
用户：例如menu等UI相关
程序：例如create init
"""
