from django import forms
from crispy_forms import layout
from website.tools import dutils
from website.views.utils import label_for_field, lookup_field, boolean_icon, display_for_field
from website.views.configs import EMPTY_CHANGELIST_VALUE, ACTION_NAME
from crispy_forms.layout import Field
from crispy_forms.utils import TEMPLATE_PACK, render_field, flatatt
from website.views.widgets import TreeCheckboxSelect, TreeRadioSelect, TreeRadioSelectLeaf
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models.base import ModelBase
from django.forms import ModelMultipleChoiceField

from django.template import loader
from django.utils.encoding import smart_str, force_str
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe


class MultiSelectFormField(forms.MultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def __init__(self, *args, **kwargs):
        self.max_choices = kwargs.pop('max_choices', 0)
        super(MultiSelectFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        if not value and self.required:
            raise forms.ValidationError(self.error_messages['required'])
        if value and self.max_choices and len(value) > self.max_choices:
            raise forms.ValidationError('You must select a maximum of %s choice%s.' % self.max_choices)
        return value


class ModelChoiceIterator(object):
    '''
    注册模型迭代器
    '''

    def __init__(self, field):
        self.field = field

    def __iter__(self):
        for m, ma in list(self.website.models_options.items()):
            yield ('%s.%s' % (m._meta.app_label, m._meta.model_name),
                   m._meta.verbose_name)


class ModelChoiceField(forms.ChoiceField):
    '''
    模型选择表单字段
    '''

    def __init__(self, required=True, widget=None, label=None, initial=None,
                 help_text=None, website=None, *args, **kwargs):
        # Call Field instead of ChoiceField __init__() because we don't need
        # ChoiceField.__init__().
        forms.Field.__init__(self, required=required, widget=widget, label=label, initial=initial, help_text=help_text,
                             *args, **kwargs)
        self.widget.choices = self.choices
        self.website = website

    def __deepcopy__(self, memo):
        result = forms.Field.__deepcopy__(self, memo)
        return result

    def _get_choices(self):
        return ModelChoiceIterator(self)

    choices = property(_get_choices, forms.ChoiceField._set_choices)

    def to_python(self, value):
        if isinstance(value, ModelBase):
            return value
        app_label, model_name = value.lower().split('.')
        return dutils.get_model(app_label, model_name)

    def prepare_value(self, value):
        if isinstance(value, ModelBase):
            value = '%s.%s' % (value._meta.app_label, value._meta.model_name)
        return value

    def valid_value(self, value):
        value = self.prepare_value(value)
        for k, v in self.choices:
            if value == smart_str(k):
                return True
        return False


class FakeMethodField:
    """
    方法型字段的包装类
    """

    def __init__(self, name, verbose_name):
        self.name = name
        self.verbose_name = verbose_name
        self.primary_key = False


class InputGroup(Field):

    template = "website/layout/input_group.tpl"

    def __init__(self, field, *args, **kwargs):
        self.field = field
        self.inputs = list(args)
        if '@@' not in args:
            self.inputs.append('@@')

        super(InputGroup, self).__init__(field, **kwargs)

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
        classes = form.fields[self.field].widget.attrs.get('class', '')
        context.update(
            {'inputs': self.inputs, 'classes': classes.replace('form-control', '')})
        if hasattr(self, 'wrapper_class'):
            context['wrapper_class'] = self.wrapper_class
        return render_field(
            self.field, form, form_style, context, template=self.template,
            attrs=self.attrs, template_pack=template_pack)


class PrependedText(InputGroup):

    def __init__(self, field, text, **kwargs):
        super(PrependedText, self).__init__(field, text, '@@', **kwargs)


class AppendedText(InputGroup):

    def __init__(self, field, text, **kwargs):
        super(AppendedText, self).__init__(field, '@@', text, **kwargs)


class PrependedAppendedText(InputGroup):

    def __init__(self, field, prepended_text=None, appended_text=None, *args, **kwargs):
        super(PrependedAppendedText, self).__init__(
            field, prepended_text, '@@', appended_text, **kwargs)


class ShowField(Field):
    template = "website/layout/field_value.tpl"

    def __init__(self, callback, *args, **kwargs):
        super(ShowField, self).__init__(*args)

        if 'attrs' in kwargs:
            self.attrs = kwargs.pop('attrs')
        if 'wrapper_class' in kwargs:
            self.wrapper_class = kwargs.pop('wrapper_class')

        self.results = [(field, callback(field)) for field in self.fields]

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK, extra_context=None, **kwargs):
        super(ShowField, self).render(form, form_style, context, template_pack, extra_context, **kwargs)
        if extra_context is None:
            extra_context = {}
        if hasattr(self, 'wrapper_class'):
            extra_context['wrapper_class'] = self.wrapper_class

        if self.attrs:
            if 'detail-class' in self.attrs:
                extra_context['input_class'] = self.attrs['detail-class']
            elif 'class' in self.attrs:
                extra_context['input_class'] = self.attrs['class']

        html = ''
        for field, result in self.results:
            extra_context['result'] = result
            if field in form.fields:
                if form.fields[field].widget != forms.HiddenInput:
                    extra_context['field'] = form[field]
                    html += loader.render_to_string(self.template, extra_context)
            else:
                extra_context['field'] = field
                html += loader.render_to_string(self.template, extra_context)
        return html


class ResultField(object):
    def __init__(self, obj, field_name, view=None):
        self.text = '&nbsp;'
        self.wraps = []
        self.allow_tags = False
        self.obj = obj
        self.view = view
        self.field_name = field_name
        self.field = None
        self.attr = None
        self.label = None
        self.value = None

        self.init()

    def init(self):
        self.label = label_for_field(self.field_name, self.obj.__class__,
                                     model_admin=self.view,
                                     return_attr=False
                                     )
        try:
            f, attr, value = lookup_field(
                self.field_name, self.obj, self.view)
        except (AttributeError, ObjectDoesNotExist):
            self.text
        else:
            if f is None:
                self.allow_tags = getattr(attr, 'allow_tags', False)
                boolean = getattr(attr, 'boolean', False)
                if boolean:
                    self.allow_tags = True
                    self.text = boolean_icon(value)
                else:
                    self.text = smart_str(value)
            else:
                if isinstance(f.remote_field, models.ManyToOneRel):
                    self.text = getattr(self.obj, f.name)
                else:
                    self.text = display_for_field(value, f)
            self.field = f
            self.attr = attr
            self.value = value

    @property
    def val(self):
        text = mark_safe(
            self.text) if self.allow_tags else conditional_escape(self.text)
        if force_str(text) == '' or text == 'None' or text == EMPTY_CHANGELIST_VALUE:
            text = mark_safe(
                '<span class="text-muted">%s</span>' % EMPTY_CHANGELIST_VALUE)
        for wrap in self.wraps:
            text = mark_safe(wrap % text)
        return text


def replace_field_to_value(layout, cb):
    for i, lo in enumerate(layout.fields):
        if isinstance(lo, Field) or issubclass(lo.__class__, Field):
            layout.fields[i] = ShowField(
                cb, *lo.fields, attrs=lo.attrs, wrapper_class=lo.wrapper_class)
        elif isinstance(lo, str):
            layout.fields[i] = ShowField(cb, lo)
        elif hasattr(lo, 'get_field_names'):
            replace_field_to_value(lo, cb)


class ReadOnlyField(Field):
    """
    crispy Field，使用在 website.receivers.detail.DetailAdminView 仅显示该字段的内容，不能编辑。
    """
    template = "website/layout/field_value.tpl"

    def __init__(self, *args, **kwargs):
        self.detail = kwargs.pop('detail')
        super(ReadOnlyField, self).__init__(*args, **kwargs)

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK, **kwargs):
        html = ''
        for field in self.fields:
            result = self.detail.get_field_result(field)
            field = {'auto_id': field}  #: 设置 field id
            html += loader.render_to_string(
                self.template, {'field': field, 'result': result})
        return html


class PermissionModelMultipleChoiceField(ModelMultipleChoiceField):
    def label_from_instance(self, p):
        def get_permission_name(p):
            action = p.codename.split('_')[0]
            if action in ACTION_NAME:
                return ACTION_NAME[action] % str(p.content_type)
            else:
                return p.name
        return get_permission_name(p)


class AdminImageField(forms.ImageField):
    def widget_attrs(self, widget):
        return {'label': self.label}


class InlineShowField(Field):
    '''
    只读显示字段
    '''
    template = "website/layout/field_value.tpl"

    def __init__(self, view, *args, **kwargs):
        super(InlineShowField, self).__init__(*args, **kwargs)
        self.view = view
        if view.style in ['table', 'gather']:
            self.template = "website/layout/field_value_td.tpl"

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK, **kwargs):
        html = ''
        detail = form.detail
        for field in self.fields:
            if not isinstance(form.fields[field].widget, forms.HiddenInput):
                result = detail.get_field_result(field)
                html += loader.render_to_string(
                    self.template, {'field': form[field], 'result': result})
        return html


class DeleteField(Field):
    '''
    用于删除控制的字段
    '''

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK, **kwargs):
        if form.instance.pk:
            self.attrs['type'] = 'hidden'
            return super(DeleteField, self).render(form, form_style, context, template_pack=TEMPLATE_PACK, **kwargs)
        else:
            return ""


class TDField(Field):
    '''
    用于以表格显示的字段
    '''
    template = "website/layout/td-field.tpl"


class Fieldset(layout.Fieldset):
    template = "website/layout/fieldset.tpl"

    def __init__(self, legend, *fields, **kwargs):
        self.description = kwargs.pop('description', None)
        self.collapsed = kwargs.pop('collapsed', None)
        super(Fieldset, self).__init__(legend, *fields, **kwargs)

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
        box_tpl = context['cl'].website.style_adminlte and 'website/includes/box_ext.tpl' or 'website/includes/box.tpl'
        self.box_tpl = box_tpl
        return super(Fieldset, self).render(form, form_style, context, template_pack=template_pack)


class InlineFormset(Fieldset):

    def __init__(self, formset, allow_blank=False, **kwargs):
        self.css_class = kwargs.pop('css_class', '')
        self.css_id = "%s-group" % formset.prefix
        self.template = formset.style.template
        self.inline_style = formset.style.name
        if allow_blank and len(formset) == 0:
            self.template = 'website/edit_inline/blank.tpl'
            self.inline_style = 'blank'
        self.formset = formset
        self.model = formset.model
        self.opts = formset.model._meta
        self.flat_attrs = flatatt(kwargs)
        self.extra_attrs = formset.style.get_attrs()

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK, **kwargs):
        context.update(dict({'formset': self, 'prefix': self.formset.prefix, 'inline_style': self.inline_style},
                            **self.extra_attrs))
        return dutils.render_to_string(
            self.template,
            context_instance=context)


class Inline(Fieldset):

    def __init__(self, rel_model):
        self.model = rel_model
        self.fields = []

    def render(self, form, form_style, context, **kwargs):
        return ""


class ModelTreeIterator(object):
    def __init__(self, field, parent=None):
        self.field = field
        self.queryset = field.queryset.filter(**{field.parent_field: parent})

    def __iter__(self):
        # if self.field.empty_label is not None:
        #    yield (u"", self.field.empty_label)
        if hasattr(self.field, 'cache_choices'):
            if self.field.choice_cache is None:
                self.field.choice_cache = [
                    self.choice(obj) for obj in self.queryset.all()
                ]
                yield self.choice
        else:
            for obj in self.queryset.all():
                yield self.choice(obj)

    def __len__(self):
        return len(self.queryset)

    def choice(self, obj):
        return (self.field.prepare_value(obj), self.field.label_from_instance(obj), ModelTreeIterator(self.field, obj))


class ModelTreeChoiceField(forms.ModelMultipleChoiceField):
    widget = TreeCheckboxSelect
    parent_field = 'parent'

    def _get_choices(self):
        if hasattr(self, '_choices'):
            return self._choices
        return ModelTreeIterator(self)

    choices = property(_get_choices, forms.ChoiceField._set_choices)


class ModelTreeChoiceFieldFK(forms.ModelChoiceField):
    widget = TreeRadioSelect
    parent_field = 'parent'

    def _get_choices(self):
        if hasattr(self, '_choices'):
            return self._choices
        return ModelTreeIterator(self)

    choices = property(_get_choices, forms.ChoiceField._set_choices)


class ModelTreeChoiceFieldFKLeaf(ModelTreeChoiceFieldFK):
    widget = TreeRadioSelectLeaf


