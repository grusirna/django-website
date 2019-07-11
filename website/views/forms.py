import django.contrib
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm
from crispy_forms.helper import FormHelper
from website.tools import dutils
from website.views.fields import ModelChoiceField
from django.core.exceptions import PermissionDenied
from django.db.models.base import ModelBase
from django.forms import ModelChoiceField
from django.http import QueryDict
from django.template import RequestContext
from django.test import RequestFactory
from django.urls import reverse, NoReverseMatch
from django.utils.http import urlencode
from django.utils.translation import ugettext as _, ugettext_lazy, ugettext_lazy as _, gettext as _, ugettext
from website.models import UserComponent, Viewmark
import website

class AdminAuthenticationForm(AuthenticationForm):
    """
    A custom authentication form used in the website app.

    """
    this_is_the_login_form = forms.BooleanField(
        widget=forms.HiddenInput, initial=1,
        error_messages={'required': ugettext_lazy("Please log in again, because your session has expired.")})

    def clean(self):
        from website.views.utils import User

        ERROR_MESSAGE = ugettext_lazy("Please enter the correct username and password "
                                      "for a staff account. Note that both fields are case-sensitive.")
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        message = ERROR_MESSAGE

        if username and password:
            self.user_cache = authenticate(
                username=username, password=password)
            if self.user_cache is None:
                if '@' in username:
                    # Mistakenly entered e-mail address instead of username? Look it up.
                    try:
                        user = User.objects.get(email=username)
                    except (User.DoesNotExist, User.MultipleObjectsReturned):
                        # Nothing to do here, moving along.
                        pass
                    else:
                        if user.check_password(password):
                            message = _("Your e-mail address is not your username."
                                        " Try '%s' instead.") % user.username
                raise forms.ValidationError(message)
            elif not self.user_cache.is_active or not self.user_cache.is_staff:
                raise forms.ValidationError(message)
        if hasattr(self, 'check_for_test_cookie'):
            self.check_for_test_cookie()
        return self.cleaned_data


class RegisterForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput)


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.PasswordInput()


class Component(forms.Form):
    '''
    区块: 本质为表单
    '''

    # 区块使用的模板
    template = 'website/components/base.tpl'
    # 描述信息
    description = 'Base Widget, don\'t use it.'

    widget_title = None
    # 区块的icon
    widget_icon = 'fa fa-plus-square'
    # 类型
    widget_type = 'website'

    base_title = None

    # 表单字段
    id = forms.IntegerField(label=_('Widget ID'), widget=forms.HiddenInput)
    title = forms.CharField(label=_('Widget Title'), required=False,
                            widget=website.views.widgets.AdminTextInputWidget)

    def __init__(self, dashboard, data):
        # 一些上下文对象
        self.dashboard = dashboard
        self.website = dashboard.website
        self.request = dashboard.request
        self.user = dashboard.request.user

        self.convert(data)
        super(Component, self).__init__(data)

        if not self.is_valid():
            raise WidgetDataError(self, self.errors.as_text())

        self.setup()

    def setup(self):
        '''
        API方法：初始化时的安装
        '''
        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False
        self.helper = helper

        self.id = self.cleaned_data['id']
        self.title = self.cleaned_data['title'] or self.base_title

        if not (self.user.is_superuser or self.has_perm()):
            raise PermissionDenied

    @property
    def widget(self):
        '''
        关键方法：输出内容,类似render
        '''
        context = {'widget_id': self.id, 'widget_title': self.title, 'widget_icon': self.widget_icon,
                   'widget_type': self.widget_type, 'form': self, 'widget': self}
        self.context(context)
        _context = RequestContext(self.request)
        _context.update(context)
        _context['box_tpl'] = self.website.style_adminlte and 'website/includes/box_ext.tpl' or 'website/includes/box.tpl'
        return dutils.render_to_string(self.template, context_instance=_context)

    def context(self, context):
        '''
        API方法：用于提供上下文变量
        '''
        pass

    def convert(self, data):
        '''
        API方法：用于将数据保存到类成员字段
        '''
        pass

    def has_perm(self):
        '''
        API方法：用于权限判断
        '''
        return False

    def save(self):
        '''
        保存表单数据
        '''
        value = dict([(f.name, f.value()) for f in self])
        user_widget = UserComponent.objects.get(id=self.id)
        user_widget.set_value(value)
        user_widget.save()

    def static(self, path):
        return self.dashboard.static(path)

    def vendor(self, *tags):
        return self.dashboard.vendor(*tags)

    def media(self):
        return forms.Media()


class ComponentManager(object):
    _widgets = None

    def __init__(self):
        self._widgets = {}

    def register(self, widget_class):
        self._widgets[widget_class.widget_type] = widget_class
        return widget_class

    def get(self, name):
        return self._widgets[name]

    def get_widgets(self, page_id):
        return list(self._widgets.values())


componentmanager = ComponentManager()


@componentmanager.register
class HtmlComponent(Component):
    widget_type = 'H5'
    widget_icon = 'fa fa-file-o'
    description = _(
        'Html Content Widget, can write any html content in widget.')

    content = forms.CharField(label=_(
        'Html Content'), widget=website.views.widgets.AdminTextareaWidget, required=False)

    def has_perm(self):
        return True

    def context(self, context):
        context['content'] = self.cleaned_data['content']


@componentmanager.register
class QuickBtnComponent(Component):
    '''
    快捷链接按钮组
    '''
    widget_type = '按钮'
    description = _('Quick button Widget, quickly open any page.')
    template = "website/components/qbutton.tpl"
    base_title = _("Quick Buttons")
    widget_icon = 'fa fa-caret-square-o-right'

    def convert(self, data):
        self.q_btns = data.pop('btns', [])

    def get_model(self, model_or_label):
        if isinstance(model_or_label, ModelBase):
            return model_or_label
        else:
            return dutils.get_model(*model_or_label.lower().split('.'))

    def context(self, context):
        btns = []
        for b in self.q_btns:
            btn = {}
            if 'model' in b:
                model = self.get_model(b['model'])
                if not self.user.has_perm("%s.view_%s" % (model._meta.app_label, model._meta.model_name)):
                    continue
                btn['url'] = reverse("%s:%s_%s_%s" % (self.website.namespace, model._meta.app_label,
                                                      model._meta.model_name, b.get('view', 'changelist')))
                btn['title'] = model._meta.verbose_name
                btn['icon'] = self.dashboard.get_menu_icon(model)
            else:
                try:
                    btn['url'] = reverse(b['url'])
                except NoReverseMatch:
                    btn['url'] = b['url']

            if 'title' in b:
                btn['title'] = b['title']
            if 'icon' in b:
                btn['icon'] = b['icon']
            btns.append(btn)

        context.update({'btns': btns})

    def has_perm(self):
        return True


class ModelFormComponent(Component):
    '''
    模型相关区块基类
    '''

    app_label = None
    model_name = None
    model_perm = 'change'

    model = ModelChoiceField(queryset=None,label=_('Target Model'), widget=website.views.widgets.SelectWidget)

    def __init__(self, dashboard, data):
        self.dashboard = dashboard
        super(ModelFormComponent, self).__init__(dashboard, data)

    def setup(self):
        self.model = self.cleaned_data['model']
        self.app_label = self.model._meta.app_label
        self.model_name = self.model._meta.model_name

        super(ModelFormComponent, self).setup()

    def has_perm(self):
        return self.dashboard.has_model_perm(self.model, self.model_perm)

    def filte_choices_model(self, model, modeladmin):
        '''
        过滤出有权限的模型
        '''
        return self.dashboard.has_model_perm(model, self.model_perm)

    def model_admin_url(self, name, *args, **kwargs):
        '''
        获取模型 name 操作的url
        '''
        return reverse(
            "%s:%s_%s_%s" % (self.website.module_name, self.app_label,
                             self.model_name, name), args=args, kwargs=kwargs)


class PartialComponent(Component):
    '''
    页面部件基类
    '''

    def get_view_class(self, view_class, model=None, **opts):
        admin_class = self.website.modelconfigs.get(model) if model else None
        return self.website.createviewclass(view_class, admin_class, **opts)

    def get_factory(self):
        return RequestFactory()

    def setup_request(self, request):
        request.user = self.user
        request.session = self.request.session
        return request

    def make_get_request(self, path, data={}, **extra):
        '''
        发起 GET 请求
        '''
        req = self.get_factory().get(path, data, **extra)
        return self.setup_request(req)

    def make_post_request(self, path, data={}, **extra):
        '''
        发起 POST 请求
        '''
        req = self.get_factory().post(path, data, **extra)
        return self.setup_request(req)


@componentmanager.register
class AddFormWidget(ModelFormComponent, PartialComponent):
    '''
    快速添加
    '''
    widget_type = '表单'
    description = _('Add any model object Widget.')
    template = "website/components/addform.tpl"
    model_perm = 'add'
    widget_icon = 'fa fa-plus'

    def setup(self):
        from website.views.views import CreateViewTemplate
        super(AddFormWidget, self).setup()

        if self.title is None:
            self.title = _('Add %s') % self.model._meta.verbose_name

        req = self.make_get_request("")
        self.add_view = self.get_view_class(
            CreateViewTemplate, self.model, list_per_page=10)(req)
        self.add_view.instance_forms()

    def context(self, context):
        helper = FormHelper()
        helper.form_tag = False
        helper.include_media = False

        context.update({
            'addform': self.add_view.form_obj,
            'addhelper': helper,
            'addurl': self.add_view.model_admin_url('add'),
            'model': self.model
        })

    def media(self):
        return self.add_view.media + self.add_view.form_obj.media + self.vendor('website.plugin.quick-form.js')


@componentmanager.register
class ListWidget(ModelFormComponent, PartialComponent):
    '''
    模型数据列表
    '''
    widget_type = '表格'
    description = _('Any Objects list Widget.')
    template = "website/components/list.tpl"
    model_perm = 'view'
    widget_icon = 'fa fa-align-justify'

    def convert(self, data):
        self.list_params = data.pop('params', {})
        self.list_count = data.pop('count', 10)

    def setup(self):
        from website.views.views import ListViewTemplate
        super(ListWidget, self).setup()

        if not self.title:
            self.title = self.model._meta.verbose_name_plural

        req = self.make_get_request("", self.list_params)
        self.list_view = self.get_view_class(ListViewTemplate, self.model)(req)
        if self.list_count:
            self.list_view.list_per_page = self.list_count

    def context(self, context):
        list_view = self.list_view
        list_view.make_result_list()

        base_fields = list_view.base_list_display
        if len(base_fields) > 5:
            base_fields = base_fields[0:5]

        context['result_headers'] = [c for c in list_view.result_headers(
        ).cells if c.field_name in base_fields]
        context['results'] = [[o for i, o in
                               enumerate([c for c in r.cells if c.field_name in base_fields])]
                              for r in list_view.results()]
        context['result_count'] = list_view.result_count
        context['page_url'] = self.model_admin_url('changelist') + "?" + urlencode(self.list_params)


@componentmanager.register
class ViewmarkWidget(PartialComponent):
    widget_type = '视图'
    widget_icon = 'fa fa-viewmark'
    description = _(
        'Viewmark Widget, can show user\'s viewmark list data in widget.')
    template = "website/components/list.tpl"

    viewmark = ModelChoiceField(
        label=_('Viewmark'), queryset=Viewmark.objects.all(), required=False)

    def setup(self):
        from website.views.views import ListViewTemplate
        Component.setup(self)

        viewmark = self.cleaned_data['viewmark']
        model = viewmark.content_type.model_class()
        data = QueryDict(viewmark.query)
        self.viewmark = viewmark

        if not self.title:
            self.title = str(viewmark)

        req = self.make_get_request("", list(data.items()))
        self.list_view = self.get_view_class(
            ListViewTemplate, model, list_per_page=10, list_editable=[])(req)

    def has_perm(self):
        return True

    def context(self, context):
        list_view = self.list_view
        list_view.make_result_list()

        base_fields = list_view.base_list_display
        if len(base_fields) > 5:
            base_fields = base_fields[0:5]

        context['result_headers'] = [c for c in list_view.makeheaders(
        ).cells if c.field_name in base_fields]
        context['results'] = [[o for i, o in
                               enumerate([c for c in r.cells if c.field_name in base_fields])]
                              for r in list_view.results()]
        context['result_count'] = list_view.result_count
        context['page_url'] = self.viewmark.url


class WidgetDataError(Exception):
    def __init__(self, widget, errors):
        super(WidgetDataError, self).__init__(str(errors))
        self.widget = widget
        self.errors = errors


@componentmanager.register
class ChartWidget(ModelFormComponent):
    widget_type = '图表'
    description = _('Show models simple chart.')
    template = 'website/components/chart.tpl'
    widget_icon = 'fa fa-bar-chart-o'

    def convert(self, data):
        self.list_params = data.pop('params', {})
        self.chart = data.pop('chart', None)

    def setup(self):
        super(ChartWidget, self).setup()

        self.charts = {}
        self.one_chart = False
        model_admin = self.website.modelconfigs[self.model]
        chart = self.chart

        if hasattr(model_admin, 'data_charts'):
            if chart and chart in model_admin.data_charts:
                self.charts = {chart: model_admin.data_charts[chart]}
                self.one_chart = True
                if self.title is None:
                    self.title = model_admin.data_charts[chart].get('title')
            else:
                self.charts = model_admin.data_charts
                if self.title is None:
                    self.title = ugettext(
                        "%s Charts") % self.model._meta.verbose_name_plural

    def filte_choices_model(self, model, modeladmin):
        return bool(getattr(modeladmin, 'data_charts', None)) and \
               super(ChartWidget, self).filte_choices_model(model, modeladmin)

    def get_chart_url(self, name, v):
        return self.model_admin_url('chart', name) + "?" + urlencode(self.list_params)

    def context(self, context):
        context.update({
            'charts': [{"name": name, "title": v['title'], 'url': self.get_chart_url(name, v)} for name, v in
                       list(self.charts.items())],
        })

    # Media
    def media(self):
        return self.vendor('flot.js', 'website.plugin.charts.js')


class ManagementForm(forms.Form):
    """
    ``ManagementForm`` is used to keep track of the current wizard step.
    """
    current_step = forms.CharField(widget=forms.HiddenInput)