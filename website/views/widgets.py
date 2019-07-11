import copy
import json
import re
import urllib.parse
from itertools import chain

from django import forms
from website.tools import dutils
from website.views.configs import BATCH_CHECKBOX_NAME
from website.views.utils import vendor
from django.conf import settings
from django.forms import Media
from django.forms.widgets import ChoiceWidget as RadioChoiceInput
from django.template import loader
from django.utils import six, formats
from django.utils.encoding import force_str, force_text
from django.utils.html import escape, conditional_escape, format_html
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.utils.translation import ugettext as _
from website.views.configs import TO_FIELD_VAR, SHOW_FIELD_VAR


# 外键字段默认使用的选择控件
# fk 外键 (多对一)
#    可选项：
#        fk_raw 打开新window页选择，系统默认为此方式
#        fk_select 下拉所有外键对象记录供选择
#        fk_ajax 通过搜索关键词ajax请求匹配得到选项，支持异步加载更多
#        fk_tree 树形下拉单选（外键到的模型的树形结构时使用）
# m2m 多对多
#    可选项：
#        m2m_raw 打开新window页选择，适用于选项极多的情况，系统默认为此方式
#        m2m_select 按住ctrl的多行选择模式
#        m2m_dropdown 下拉CheckBox选择，一般适用于选项较少的情况
#        m2m_transfer 左右两边移动选择
#
#        m2m_select2 下拉所有对象供多选，可本地搜索匹配
#        m2m_ajax 通过搜索关键词ajax请求匹配得到选项,支持异步加载更多，只选一个
#        m2m_ajax_multi 通过搜索关键词ajax请求匹配得到选项,支持异步加载更多，可选多个
#        m2m_tree 树形下拉多选（外键到的模型的树形结构时使用）
class RawIdWidget(forms.TextInput):
    label_format = '<input type="text" id="id_%s_show" class="form-control" value="%s" readonly="readonly" />'

    def render(self, name, value, attrs=None):
        to_opts = self.r_model._meta

        if attrs is None:
            attrs = {}
        extra = []
        if 1:  # self.r_model in self.view.website.modelconfigs:
            from website.views.views import ListViewTemplate
            if issubclass(self.r_model, ListViewTemplate):
                related_url = self.r_model.get_block_url()
            else:
                related_url = self.view.get_site_url(
                    '%s_%s_changelist' % (to_opts.app_label, to_opts.model_name))

            params = self.url_parameters(name)
            if params:
                url = '?' + '&amp;'.join(['%s=%s' % (k, v) for k, v in list(params.items())])
            else:
                url = ''
            if "class" not in attrs:
                attrs['class'] = 'vForeignKeyRawIdAdminField'  # The JavaScript code looks for this hook.

            if value:
                if attrs['class'] == 'vManyToManyRawIdAdminField':
                    self.label_format = '<div class="obj-show " id="id_%s_show">%s</div>'
                input_html = self.label_for_value(value, name=name)
            else:
                if attrs['class'] == 'vManyToManyRawIdAdminField':
                    input_html = '<div class="obj-show " id="id_%s_show"></div>' % name
                else:
                    input_html = '<input type="text" id="id_%s_show" class="form-control" value="" readonly="readonly" />' % name
            _css = attrs['class'] == 'vManyToManyRawIdAdminField' and 'm2m-field' or 'fk-field'
            all_html = '''
            <div class="input-group %s">
                %s
                <span class="input-group-btn vertical-top">
                    <a href="%s%s" class="btn btn-primary related-lookup spa-expect-links" id="lookup_id_%s" onclick="return showRelatedObjectLookupPopup(this);"><i class="fa fa-search"></i></a>
                    <a href="javascript://" class="btn btn-default related-lookup" id="remove_id_%s"  onclick="return removeRelatedObject(this);" ><i class="fa fa-remove"></i></a>
                </span>
            </div>
            ''' % (_css, input_html, related_url, url, name, name)
            extra.append(all_html)

        attrs['type'] = 'hidden'
        output = [super(RawIdWidget, self).render(name, value, attrs)] + extra

        return mark_safe(''.join(output))

    def _render_label(self, name, value):
        return self.label_format % (name, escape(Truncator(value).words(14, truncate='...')))

    @property
    def media(self):
        return vendor('website.widget.RelatedObjectLookups.js', 'website.widget.select-related.css')


class ReadonlyWidget(forms.TextInput):
    def __init__(self, attrs=None):
        if attrs:
            attrs['readonly'] = 'readonly'
        else:
            attrs = {'readonly': 'readonly'}
        super(ReadonlyWidget, self).__init__(attrs)


class DateWidget(forms.DateInput):
    @property
    def media(self):
        return vendor('datepicker.js', 'datepicker.css', 'website.widget.datetime.js')

    def __init__(self, attrs=None, format=None):
        final_attrs = {'class': 'date-field', 'size': '10'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(DateWidget, self).__init__(attrs=final_attrs, format=format)

    def render(self, name, value, attrs=None):
        input_html = super(DateWidget, self).render(name, value, attrs)
        return mark_safe(
            '<div class="input-group date bootstrap-datepicker"><span class="input-group-addon"><i class="fa fa-calendar"></i></span>%s'
            '<span class="input-group-btn"><button class="btn btn-default" type="button">%s</button></span></div>' % (
                input_html, _('Today')))


AdminDateWidget = DateWidget


class TimeWidget(forms.TimeInput):
    @property
    def media(self):
        return vendor('datepicker.js', 'timepicker.js', 'timepicker.css', 'website.widget.datetime.js')

    def __init__(self, attrs=None, format=None):
        final_attrs = {'class': 'time-field', 'size': '8'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(TimeWidget, self).__init__(attrs=final_attrs, format=format)

    def render(self, name, value, attrs=None):
        input_html = super(TimeWidget, self).render(name, value, attrs)
        return mark_safe(
            '<div class="input-group time bootstrap-timepicker"><span class="input-group-addon"><i class="fa fa-clock-o">'
            '</i></span>%s<span class="input-group-btn"><button class="btn btn-default" type="button">%s</button></span></div>' % (
                input_html, _('Now')))


AdminTimeWidget = TimeWidget


class SelectWidget(forms.Select):
    @property
    def media(self):
        return vendor('select.js', 'select.css', 'website.widget.select.js')


AdminSelectWidget = SelectWidget


class SelectModelWidget(forms.Select):
    def __init__(self, model, key, value, attrs=None, choices=()):
        super(SelectModelWidget, self).__init__(attrs)
        self.model = model
        self.choices = list(model.objects.values_list(key, value))

    @property
    def media(self):
        return vendor('select.js', 'select.css', 'website.widget.select.js')


class AjaxSearchWidget(forms.TextInput):
    def __init__(self, data_source, attrs=None, using=None):
        self.data_source = data_source
        super(AjaxSearchWidget, self).__init__(attrs)

    def render(self, name, value, attrs=None):
        if attrs is None:
            attrs = {}
        if "class" not in attrs:
            attrs['class'] = 'select-search'
        else:
            attrs['class'] = attrs['class'] + ' select-search'
        attrs['data-search-url'] = self.data_source
        attrs['data-placeholder'] = '输入查找'
        attrs['data-choices'] = '?'
        if value:
            attrs['data-label'] = self.label_for_value(value)

        return super(AjaxSearchWidget, self).render(name, value, attrs)

    def label_for_value(self, value):

       key = self.remote_field.name
       try:
           obj = self.remote_field.model._default_manager.using(
               self.db).get(**{key: value})
           return '%s' % escape(Truncator(obj).words(14, truncate='...'))
       except (ValueError, self.remote_field.model.DoesNotExist):
           return ""

    @property
    def media(self):
        return vendor('select.js', 'select.css', 'website.widget.select.js')


class SplitDateTime(forms.SplitDateTimeWidget):
    """
    A SplitDateTime Widget that has some website-specific styling.
    """

    def __init__(self, attrs=None):
        widgets = [DateWidget, TimeWidget]
        # Note that we're calling MultiWidget, not SplitDateTimeWidget, because
        # we want to define widgets.
        forms.MultiWidget.__init__(self, widgets, attrs)

    def format_output(self, rendered_widgets):
        return mark_safe('<div class="datetime clearfix">%s%s</div>' %
                         (rendered_widgets[0], rendered_widgets[1]))


AdminSplitDateTime = SplitDateTime


class AdminRadioInput(RadioChoiceInput):
    def render(self, name=None, value=None, attrs=None, choices=()):
        name = name or self.name
        value = value or self.value
        attrs = attrs or self.attrs
        attrs['class'] = attrs.get('class', '').replace('form-control', '')
        if 'id' in self.attrs:
            label_for = ' for="%s_%s"' % (self.attrs['id'], self.index)
        else:
            label_for = ''
        choice_label = conditional_escape(force_str(self.choice_label))
        if attrs.get('inline', False):
            return mark_safe('<label%s class="radio-inline">%s %s</label>' % (label_for, self.tag(), choice_label))
        else:
            return mark_safe('<div class="radio"><label%s>%s %s</label></div>' % (label_for, self.tag(), choice_label))


class AdminRadioFieldRenderer(forms.RadioSelect):
    def __iter__(self):
        for i, choice in enumerate(self.choices):
            yield AdminRadioInput(self.name, self.value, self.attrs.copy(), choice, i)

    def __getitem__(self, idx):
        choice = self.choices[idx]  # Let the IndexError propogate
        return AdminRadioInput(self.name, self.value, self.attrs.copy(), choice, idx)

    def render(self):
        return mark_safe('\n'.join([force_str(w) for w in self]))


class AdminRadioSelect(forms.RadioSelect):
    renderer = AdminRadioFieldRenderer


class AdminCheckboxSelect(forms.CheckboxSelectMultiple):
    def render(self, name, value, attrs=None, choices=()):
        if value is None:
            value = []
        has_id = attrs and 'id' in attrs
        final_attrs = self.build_attrs(attrs, name=name)
        output = []
        # Normalize to strings
        str_values = set([force_str(v) for v in value])
        for i, (option_value, option_label) in enumerate(chain(self.choices, choices)):
            # If an ID attribute was given, add a numeric index as a suffix,
            # so that the checkboxes don't all have the same ID attribute.
            if has_id:
                final_attrs = dict(final_attrs, id='%s_%s' % (attrs['id'], i))
                label_for = ' for="%s"' % final_attrs['id']
            else:
                label_for = ''

            cb = forms.CheckboxInput(
                final_attrs, check_test=lambda value: value in str_values)
            option_value = force_str(option_value)
            rendered_cb = cb.render(name, option_value)
            option_label = conditional_escape(force_str(option_label))

            if final_attrs.get('inline', False):
                output.append(
                    '<label%s class="checkbox-inline">%s %s</label>' % (label_for, rendered_cb, option_label))
            else:
                output.append(
                    '<div class="checkbox"><label%s>%s %s</label></div>' % (label_for, rendered_cb, option_label))
        return mark_safe('\n'.join(output))


class AdminSelectMultiple(forms.SelectMultiple):
    def __init__(self, attrs=None):
        final_attrs = {'class': 'select-multi'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(AdminSelectMultiple, self).__init__(attrs=final_attrs)


class AdminFileWidget(forms.ClearableFileInput):
    template_with_initial = ('<p class="file-upload">%s</p>'
                             % forms.ClearableFileInput.initial_text)
    template_with_clear = ('<span class="clearable-file-input">%s</span>'
                           % forms.ClearableFileInput.clear_checkbox_label)


class AdminTextareaWidget(forms.Textarea):
    def __init__(self, attrs=None):
        final_attrs = {'class': 'textarea-field', 'rows': 3}
        if attrs is not None:
            final_attrs.update(attrs)
        super(AdminTextareaWidget, self).__init__(attrs=final_attrs)


class AdminTextInputWidget(forms.TextInput):
    def __init__(self, attrs=None):
        final_attrs = {'class': 'text-field'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(AdminTextInputWidget, self).__init__(attrs=final_attrs)


class MultiTextInputWidget(forms.TextInput):
    def __init__(self, attrs=None):
        final_attrs = {'class': 'text-field'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(MultiTextInputWidget, self).__init__(attrs=final_attrs)

    def _format_value(self, value):
        if value:
            value = list(map(str, value))
            return ','.join(value)
        else:
            return ''

    def value_from_datadict(self, data, files, name):
        value = data.get(name)
        if value:
            return value.split(',')


class AdminURLFieldWidget(forms.TextInput):
    def __init__(self, attrs=None):
        final_attrs = {'class': 'url-field'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(AdminURLFieldWidget, self).__init__(attrs=final_attrs)


class AdminIntegerFieldWidget(forms.TextInput):
    def __init__(self, attrs=None):
        final_attrs = {'class': 'int-field'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(AdminIntegerFieldWidget, self).__init__(attrs=final_attrs)


class AdminCommaSeparatedIntegerFieldWidget(forms.TextInput):
    def __init__(self, attrs=None):
        final_attrs = {'class': 'sep-int-field'}
        if attrs is not None:
            final_attrs.update(attrs)
        super(AdminCommaSeparatedIntegerFieldWidget,
              self).__init__(attrs=final_attrs)


class SelectRelation(forms.TextInput):
    '''
    使用示例：
    widget=SelectRelation(self, 'select1', {
                                     '1':  ForeignKeyPopupWidget(self, Host, 'id'),
                                     '2':  ForeignKeyPopupWidget(self, A, 'id'),
                                     '3':  ForeignKeyPopupWidget(self, B, 'id'),
                                     }
                            )

    '''

    def __init__(self, view, link, map_dict, attrs=None, using=None, inline_ref=''):
        self.view = view
        self.link = link
        self.map_dict = map_dict
        self.inline_ref = inline_ref
        super(SelectRelation, self).__init__(attrs)

    def value_from_datadict(self, data, files, name):
        return data.get(name)
        link_val = data.get(self.link)
        cur_obj = self.map_dict[link_val]
        return cur_obj.value_from_datadict(data, files, name)

    def render(self, name, value, attrs=None, form=None):
        link_val = self.get_value(self.link, form)
        link_val = str(link_val)
        map_list = [(str(k), '%s-%s' % (self.link, id(v))) for k, v in list(self.map_dict.items())]
        _map = dict(map_list)
        if link_val and link_val != 'None':
            cur_obj = self.map_dict.get(link_val, None)
        else:
            cur_obj = None
        _all = set(self.map_dict.values())
        output = []
        if self.inline_ref + '-__prefix__-' in name:
            _name = name.replace(self.inline_ref + '-__prefix__-', '')
        else:
            _name = re.sub(self.inline_ref + '-\d+-', '', name)
        _link = name.replace(_name, self.link)  # 'id_items-__prefix__-'+self.link
        for obj in _all:
            if obj == cur_obj:
                output.append('''<div id="id_%s-%s">%s</div>''' % (_link, id(obj), obj.render(name, value, attrs)))
            else:
                output.append('''<div id="id_%s-%s" style="display:none">%s</div>''' % (
                    _link, id(obj), obj.render(name, None, attrs)))
        opt_list = ['<li key="%s">%s</li>' % (k, v) for k, v in list(_map.items())]
        output.append('''
                      <ul class="select-relation" name="%s" link="%s" style="display:none">%s</ul>
        ''' % (_name, self.link, ''.join(opt_list)))
        return ''.join(output)

    def get_value(self, key, form=None):
        '''
        得到关联字段的值
        '''
        if hasattr(self.view, 'form_obj'):
            self.form = self.view.form_obj
        else:
            self.form = form
        if not self.form.is_bound:
            return self.form.initial.get(key, None)
        else:
            return self.form.data.get(key, None)

    @property
    def media(self):
        media = Media()
        _all = set(self.map_dict.values())
        for obj in _all:
            media = media + obj.media
        return media + vendor('website.widget.selectrelation.js')


def url_params_from_lookup_dict(lookups):
    """
    Converts the type of lookups specified in a ForeignKey limit_choices_to
    attribute to a dictionary of query parameters
    """
    params = {}
    if lookups and hasattr(lookups, 'items'):
        items = []
        for k, v in list(lookups.items()):
            if isinstance(v, (tuple, list)):
                v = ','.join([str(x) for x in v])
            elif isinstance(v, bool):
                # See django.db.fields.BooleanField.get_prep_lookup
                v = ('0', '1')[v]
            else:
                v = six.text_type(v)
            items.append((k, v))
        params.update(dict(items))
    return params


class ForeignKeySearchWidget(forms.TextInput):
    '''select2下拉选择, ajax请求数据'''

    def __init__(self, rel, view, attrs=None, using=None):
        self.rel = rel
        self.r_model = rel.model

        self.view = view
        self.db = using
        super(ForeignKeySearchWidget, self).__init__(attrs)

    def render(self, name, value, attrs=None):
        to_opts = self.r_model._meta
        if attrs is None:
            attrs = {}
        if "class" not in attrs:
            attrs['class'] = 'select-search'
        else:
            attrs['class'] = attrs['class'] + ' select-search'
        attrs['data-search-url'] = self.view.get_site_url(
            '%s_%s_changelist' % (to_opts.app_label, to_opts.model_name))
        attrs['data-placeholder'] = _('搜索 %s') % to_opts.verbose_name
        attrs['data-choices'] = '?'
        if self.rel.limit_choices_to:
            for i in list(self.rel.limit_choices_to):
                attrs['data-choices'] += "&_p_%s=%s" % (i, self.rel.limit_choices_to[i])
            attrs['data-choices'] = format_html(attrs['data-choices'])
        if value:
            attrs['data-label'] = self.label_for_value(value)

        return super(ForeignKeySearchWidget, self).render(name, value, attrs)

    def label_for_value(self, value):
        key = self.rel.get_related_field().name
        try:
            obj = self.r_model._default_manager.using(
                self.db).get(**{key: value})
            return '%s' % escape(Truncator(obj).words(14, truncate='...'))
        except (ValueError, self.r_model.DoesNotExist):
            return ""

    @property
    def media(self):
        return vendor('select.js', 'select.css', 'website.widget.select.js')


class ForeignKeyRawIdWidget(RawIdWidget):
    """
    打开Window窗口选择对象将id, title带过来 (单选)
    """

    def __init__(self, rel, view, attrs=None, using=None):
        self.rel = rel
        self.r_model = rel.model

        self.view = view
        self.db = using
        super(ForeignKeyRawIdWidget, self).__init__(attrs)

    def base_url_parameters(self):
        return url_params_from_lookup_dict(self.rel.limit_choices_to)

    def url_parameters(self, name=None):
        params = self.base_url_parameters()
        if hasattr(self.view, 'fk_url_param'):
            m_param = self.view.fk_url_param
            if name in list(m_param.keys()):
                params.update(m_param[name])
        params.update({TO_FIELD_VAR: self.rel.get_related_field().name})
        return params

    def label_for_value(self, value, name=None):
        key = self.rel.get_related_field().name
        try:
            obj = self.r_model._default_manager.using(self.db).get(**{key: value})
            return self._render_label(name, obj)
        except (ValueError, self.r_model.DoesNotExist):
            return ''


class ManyToManyRawIdWidget(ForeignKeyRawIdWidget):
    """
    打开Window窗口选择对象将id, title带过来 (多选)
    """

    def render(self, name, value, attrs=None):
        if attrs is None:
            attrs = {}
        attrs['class'] = 'vManyToManyRawIdAdminField'
        if type(value) in (list, tuple):
            value = ','.join([force_text(v) for v in value])
        return super(ManyToManyRawIdWidget, self).render(name, value, attrs)

    def label_for_value(self, value, name=None):
        m_value = value.split(',')
        m_value = [e for e in m_value if e]
        key = self.rel.get_related_field().name
        objs = objs = self.r_model._default_manager.using(self.db).filter(**{key + '__in': m_value})
        li_format = '''<a class="btn btn-sm" onclick="removeSingleObject(this,'%s', '%s');">%s</a>'''
        tar_list = ''
        for obj in objs:
            show_val = escape(Truncator(obj).words(14, truncate='...'))
            val = getattr(obj, key)
            tar_list += li_format % ('id_' + name, val, show_val)
        return self.label_format % (name, tar_list)

    def value_from_datadict(self, data, files, name):
        value = data.get(name)
        if value:
            return value.split(',')

    def _has_changed(self, initial, data):
        if initial is None:
            initial = []
        if data is None:
            data = []
        if len(initial) != len(data):
            return True
        for pk1, pk2 in zip(initial, data):
            if force_text(pk1) != force_text(pk2):
                return True
        return False


class ForeignKeyPopupWidget(RawIdWidget):
    """
    打开div窗口 选择对象 设置id, title (单选)
    """

    def __init__(self, view, r_model, t_name, s_name=None, attrs=None, using=None):
        self.r_model = r_model
        self.t_name = t_name
        self.s_name = s_name

        self.view = view
        self.db = using
        super(ForeignKeyPopupWidget, self).__init__(attrs)

    def url_parameters(self, name=None):
        params = {}
        if hasattr(self.view, 'fk_url_param'):
            m_param = self.view.fk_url_param
            if name in list(m_param.keys()):
                params.update(m_param[name])
        params[TO_FIELD_VAR] = self.t_name
        if self.s_name:
            params[SHOW_FIELD_VAR] = self.s_name
        return params

    def label_for_value(self, value, name=None):
        key = self.t_name
        from website.views.views import ListViewTemplate
        if issubclass(self.r_model, ListViewTemplate):
            return self._render_label(name, self.r_model.queryset_class().verbose(value))
        else:
            try:
                obj = self.r_model._default_manager.using(self.db).get(**{key: value})
                if self.s_name:
                    show_val = getattr(obj, self.s_name)
                    if callable(show_val): show_val = show_val()
                else:
                    show_val = obj
                return self._render_label(name, show_val)
            except (ValueError, self.r_model.DoesNotExist):
                return self._render_label(name, '')


class ManyToManyPopupWidget(ForeignKeyPopupWidget):
    """
    打开div窗口 选择对象 设置id, title (多选)
    """

    def render(self, name, value, attrs=None):
        if attrs is None:
            attrs = {}
        attrs['class'] = 'vManyToManyRawIdAdminField'
        if type(value) in (list, tuple):
            value = ','.join([force_text(v) for v in value])
        return super(ManyToManyPopupWidget, self).render(name, value, attrs)

    def label_for_value(self, value, name=None):
        m_value = value.split(',')
        m_value = [e for e in m_value if e]
        key = self.t_name
        objs = self.r_model._default_manager.using(self.db).filter(**{key + '__in': m_value})
        li_format = '''<a class="btn btn-sm" onclick="removeSingleObject(this,'%s', '%s');">%s</a>'''
        tar_list = ''
        for obj in objs:
            if self.s_name:
                show_val = getattr(obj, self.s_name)
                if callable(show_val): show_val = show_val()
                show_val = escape(Truncator(show_val).words(14, truncate='...'))
            else:
                show_val = escape(Truncator(obj).words(14, truncate='...'))
            val = getattr(obj, key)
            tar_list += li_format % ('id_' + name, val, show_val)
        return self.label_format % (name, tar_list)

    def value_from_datadict(self, data, files, name):
        value = data.get(name)
        return value


class SelectMultipleTransfer(forms.SelectMultiple):
    """
    左右转移选择控件 (多选)
    """

    @property
    def media(self):
        return vendor('website.widget.select-transfer.js', 'website.widget.select-transfer.css')

    def __init__(self, verbose_name, is_stacked, attrs=None, choices=()):
        self.verbose_name = verbose_name
        self.is_stacked = is_stacked
        super(SelectMultipleTransfer, self).__init__(attrs, choices)

    def render_opt(self, selected_choices, option_value, option_label):
        option_value = force_str(option_value)
        return '<option value="%s">%s</option>' % (
            escape(option_value), conditional_escape(force_str(option_label))), bool(
            option_value in selected_choices)

    def render(self, name, value, attrs=None, choices=()):
        if attrs is None:
            attrs = {}
        attrs['class'] = ''
        if self.is_stacked:
            attrs['class'] += 'stacked'
        if value is None:
            value = []
        final_attrs = self.build_attrs(attrs, extra_attrs={'name': name})

        selected_choices = set(force_str(v) for v in value)
        available_output = []
        chosen_output = []

        for option_value, option_label in chain(self.choices, choices):
            if isinstance(option_label, (list, tuple)):
                available_output.append('<optgroup label="%s">' %
                                        escape(force_str(option_value)))
                for option in option_label:
                    output, selected = self.render_opt(
                        selected_choices, *option)
                    if selected:
                        chosen_output.append(output)
                    else:
                        available_output.append(output)
                available_output.append('</optgroup>')
            else:
                output, selected = self.render_opt(
                    selected_choices, option_value, option_label)
                if selected:
                    chosen_output.append(output)
                else:
                    available_output.append(output)

        context = {
            'verbose_name': self.verbose_name,
            'attrs': attrs,
            'field_id': attrs['id'],
            'flatatts': dutils.flatatt(final_attrs),
            'available_options': '\n'.join(available_output),
            'chosen_options': '\n'.join(chosen_output),
        }
        return mark_safe(loader.render_to_string('website/forms/transfer.tpl', context))


class SelectMultipleDropdown(forms.SelectMultiple):
    """
    下拉勾选控件 (多选)
    """

    @property
    def media(self):
        return vendor('multiselect.js', 'multiselect.css', 'website.widget.multiselect.js')

    def render(self, name, value, attrs=None):
        if attrs is None:
            attrs = {}
        attrs['class'] = 'selectmultiple selectdropdown'
        return super(SelectMultipleDropdown, self).render(name, value, attrs)


class SelectMultipleDropselect(forms.SelectMultiple):
    """
    select2下拉选择控件 同步加载所有数据 (多选)
    """

    @property
    def media(self):
        return vendor('select.js', 'select.css', 'website.widget.select.js')

    def render(self, name, value, attrs=None):
        if attrs is None:
            attrs = {}
        attrs['class'] = 'select2dropdown'
        attrs['multiple'] = 'multiple'
        return super(SelectMultipleDropselect, self).render(name, value, attrs)


class SelectMultipleAjax(forms.SelectMultiple):
    """
    select2下拉选择控件 异步加载 (单选/多选)
    """

    def __init__(self, rel, view, multiple, attrs=None):
        self.rel = rel
        self.view = view
        self.multiple = multiple
        super(SelectMultipleAjax, self).__init__(attrs)

    def value_from_datadict(self, data, files, name):
        m_data = data.get(name, None)
        if m_data:
            m_list = m_data.split(',')
            return [int(k) for k in m_list if k]
        else:
            return []

    def _format_value(self, value):
        if self.is_localized:
            return formats.localize_input(value)
        value = [str(e) for e in value]
        return ','.join(value)

    def label_for_value(self, value):
        key = self.remote_field.name
        q_dict = {}
        q_dict[key + '__in'] = value
        objs = self.remote_field.model._default_manager.filter(**q_dict)
        if self.multiple:
            return json.dumps([{'id': e.pk, '__str__': escape(Truncator(e).words(14, truncate='...'))} for e in objs])
        else:
            if objs:
                obj = objs[0]
                return json.dumps({'id': obj.pk, '__str__': escape(Truncator(obj).words(14, truncate='...'))})
            else:
                return ''

    @property
    def media(self):
        return vendor('select.js', 'select.css', 'website.widget.select.js')

    def render(self, name, value, attrs=None):

        to_opts = self.remote_field.model._meta
        if attrs is None:
            attrs = {}
        attrs['class'] = 'select2ajax'
        if self.multiple:
            attrs['multiple'] = 'multiple'
        attrs['data-search-url'] = self.view.get_site_url(
            '%s_%s_changelist' % (to_opts.app_label, to_opts.model_name))
        attrs['data-placeholder'] = _('搜索 %s') % to_opts.verbose_name
        attrs['data-choices'] = '?'
        if self.rel.limit_choices_to:
            for i in list(self.rel.limit_choices_to):
                attrs['data-choices'] += "&_p_%s=%s" % (i, self.rel.limit_choices_to[i])
            attrs['data-choices'] = format_html(attrs['data-choices'])
        if value:
            attrs['data-label'] = self.label_for_value(value)

        if value is None:
            value = ''
        final_attrs = self.build_attrs(attrs, type='text', name=name)
        if value != '':
            # Only add the 'value' attribute if a value is non-empty.
            final_attrs['value'] = force_text(self._format_value(value))
        return format_html('<input{0} />', dutils.flatatt(final_attrs))


class WidgetTypeSelect(forms.Widget):
    def __init__(self, widgets, attrs=None):
        super(WidgetTypeSelect, self).__init__(attrs)
        self._widgets = widgets

    def render(self, name, value, attrs=None):
        if value is None:
            value = ''
        final_attrs = self.build_attrs(attrs, dict(name=name))
        final_attrs['class'] = 'nav nav-pills nav-stacked'
        output = ['<ul%s>' % dutils.flatatt(final_attrs)]
        options = self.render_options(force_str(value), final_attrs['id'])
        if options:
            output.append(options)
        output.append('</ul>')
        output.append('<input type="hidden" id="%s_input" name="%s" value="%s"/>' %
                      (final_attrs['id'], name, force_str(value)))
        return mark_safe('\n'.join(output))

    def render_option(self, selected_choice, widget, id):
        if widget.widget_type == selected_choice:
            selected_html = ' class="active"'
        else:
            selected_html = ''
        return ('<li%s><a onclick="' +
                'javascript:$(this).parent().parent().find(\'>li\').removeClass(\'active\');$(this).parent().addClass(\'active\');' +
                '$(\'#%s_input\').attr(\'value\', \'%s\')' % (id, widget.widget_type) +
                '"><h4><i class="%s"></i> %s</h4><p>%s</p></a></li>') % (
                   selected_html,
                   widget.widget_icon,
                   widget.widget_title or widget.widget_type,
                   widget.description)

    def render_options(self, selected_choice, id):
        # Normalize to strings.
        output = []
        for widget in self._widgets:
            output.append(self.render_option(selected_choice, widget, id))
        return '\n'.join(output)


class ChangeFieldWidgetWrapper(forms.Widget):
    def __init__(self, widget):
        self.is_hidden = widget.is_hidden
        self.needs_multipart_form = widget.needs_multipart_form
        self.attrs = widget.attrs
        self.widget = widget

    def __deepcopy__(self, memo):
        obj = copy.copy(self)
        obj.widget = copy.deepcopy(self.widget, memo)
        obj.attrs = self.widget.attrs
        memo[id(self)] = obj
        return obj

    @property
    def media(self):
        media = self.widget.media + vendor('website.plugin.batch.js')
        return media

    def render(self, name, value, attrs=None):
        output = []
        is_required = self.widget.is_required
        output.append('<label class="btn btn-info btn-xs">'
                      '<input type="checkbox" class="batch-field-checkbox" name="%s" value="%s"%s/> %s</label>' %
                      (BATCH_CHECKBOX_NAME, name, (is_required and ' checked="checked"' or ''), _('Change this field')))
        output.extend([('<div class="control-wrap" style="margin-top: 10px;%s" id="id_%s_wrap_container">' %
                        ((not is_required and 'display: none;' or ''), name)),
                       self.widget.render(name, value, attrs), '</div>'])
        return mark_safe(''.join(output))

    def build_attrs(self, extra_attrs=None, **kwargs):
        "Helper function for building an attribute dictionary."
        self.attrs = self.widget.build_attrs(extra_attrs=None, **kwargs)
        return self.attrs

    def value_from_datadict(self, data, files, name):
        return self.widget.value_from_datadict(data, files, name)

    def id_for_label(self, id_):
        return self.widget.id_for_label(id_)


class RelatedFieldWidgetWrapper(forms.Widget):
    """
    This class is a wrapper to a given widget to add the add icon for the
    website interface.
    """

    def __init__(self, widget, rel, add_url, rel_add_url):
        try:
            self.is_hidden = widget.is_hidden
        except:
            pass
        self.needs_multipart_form = widget.needs_multipart_form
        self.attrs = widget.attrs
        self.choices = widget.choices
        self.is_required = widget.is_required
        self.widget = widget
        self.rel = rel

        self.add_url = add_url
        self.rel_add_url = rel_add_url

    def __deepcopy__(self, memo):
        obj = copy.copy(self)
        obj.widget = copy.deepcopy(self.widget, memo)
        obj.attrs = self.widget.attrs
        memo[id(self)] = obj
        return obj

    @property
    def media(self):
        media = self.widget.media + vendor('website.plugin.quick-form.js')
        return media

    def render(self, name, value, *args, **kwargs):
        self.widget.choices = self.choices
        output = []
        if self.add_url:
            output.append(
                '<a href="%s" title="%s" class="btn btn-primary btn-sm btn-ajax pull-right" data-for-id="id_%s" data-refresh-url="%s"><i class="fa fa-plus"></i></a>'
                % (
                    self.add_url, (_('Create New %s') % self.rel.model._meta.verbose_name), name,
                    "%s?_field=%s&%s=" % (self.rel_add_url, name, name)))
        self.widget.attrs['class'] = self.attrs.get('class', '')
        if 'renderer' in kwargs:
            kwargs.pop('renderer')
        output.extend(['<div class="control-wrap" id="id_%s_wrap_container">' % name,
                       self.widget.render(name, value, *args, **kwargs), '</div>'])
        return mark_safe(''.join(output))

    def build_attrs(self, extra_attrs=None, **kwargs):
        "Helper function for building an attribute dictionary."
        self.attrs = self.widget.build_attrs(extra_attrs=None, **kwargs)
        return self.attrs

    def value_from_datadict(self, data, files, name):
        return self.widget.value_from_datadict(data, files, name)

    def id_for_label(self, id_):
        return self.widget.id_for_label(id_)


class TreeSelect(object):
    def fill_output(self, output, choices, str_values, label_list):
        if len(choices):
            output.append('<ul>')
            for (option_value, option_label, children) in choices:
                option_value = force_str(option_value)
                option_label = conditional_escape(force_str(option_label))

                children_output = []
                self.fill_output(children_output, children, str_values, label_list)

                classes = []
                if children_output:
                    classes.append('jstree-open')
                if option_value in str_values:
                    classes.append('jstree-checked')
                    label_list.append(option_label)

                output.append('<li value="%s" label="%s" class="%s"><a href="javascript:void(0);">%s</a>' % \
                              (option_value, option_label, " ".join(classes), option_label))
                if children_output:
                    output.extend(children_output)
                output.append('</li>')

            output.append('</ul>')

    def render(self, name, value, attrs=None):
        if value is None: value = []
        if self.base_css == 'website-fk-tree-leaf':
            _base_css = "website-fk-tree leaf"
        else:
            _base_css = self.base_css
        if attrs:
            attrs['class'] = attrs.get('class', '') + ' %s open' % _base_css
        else:
            attrs['class'] = '%s open' % _base_css

        final_attrs = self.build_attrs(attrs, name=name)
        label_list = []
        output = [
            '<div class="dropdown-menu jstree-container"><input type="search" placeholder="Search" id="jstree-search"></input><div%s role="combobox">' % dutils.flatatt(
                final_attrs)]
        # Normalize to strings
        if self.base_css == 'website-m2m-tree':
            str_values = set([force_str(v) for v in value])
        else:
            if value:
                str_values = [force_str(value)]
            else:
                str_values = []
        self.fill_output(output, self.choices, str_values, label_list)
        raw_str = ''
        if self.base_css in ['website-fk-tree', 'website-fk-tree-leaf']:
            raw_str = '<input type="hidden" id="id_%s" name="%s" value="%s"></input>' % (
                name, name, str_values and str_values.pop() or '')
        output.append('</div></div>')

        wapper = '''
<div class="dropdown">%s
<button type="button" class="btn dropdown-toggle btn-default bs-placeholder" data-toggle="dropdown" role="button" title="点击下拉选择" aria-expanded="true"><span class="filter-option pull-left">%s</span>&nbsp;<span class="bs-caret"><span class="caret"></span></span></button>
        ''' % (raw_str, (', '.join(label_list) or '请选择...'))
        output.insert(0, wapper)
        output.append('</div>')

        return mark_safe('\n'.join(output))


class TreeCheckboxSelect(TreeSelect, forms.CheckboxSelectMultiple):
    base_css = 'website-m2m-tree'
    pass


class TreeRadioSelect(TreeSelect, forms.RadioSelect):
    base_css = 'website-fk-tree'
    pass


class TreeRadioSelectLeaf(TreeSelect, forms.RadioSelect):
    base_css = 'website-fk-tree-leaf'
    pass


class ImageWidget(forms.FileInput):
    """
    A ImageField Widget that shows its current value if it has one.
    """

    def __init__(self, attrs={}):
        super(ImageWidget, self).__init__(attrs)

    def render(self, name, value, attrs=None):
        output = []
        if value:
            db_value = str(value)
            if db_value.startswith('/'):
                file_path = urllib.parse.urljoin(settings.REMOTE_MEDIA_URL, db_value)
            elif hasattr(value, "url"):
                file_path = value.url
            else:
                file_path = ''
            label = self.attrs.get('label', name)
            output.append('<img src="%s" onclick="$(\'#id_%s\').click()" class="field_img"/>' % (file_path, name))
        else:
            output.append(
                '<img src="/static/website/img/upload_default.png" onclick="$(\'#id_%s\').click()" class="field_img"/>' % name)
        attrs['class'] = 'img-file-ext'
        # attrs['onChange'] = 'previewImage(this)'
        output.append(super(ImageWidget, self).render(name, value, attrs))
        return mark_safe(''.join(output))
