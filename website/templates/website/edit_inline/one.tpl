{% extends "website/edit_inline/base.tpl" %}
{% load i18n website_tags crispy_forms_tags %}

{% block box_title %}{{ formset.opts.verbose_name_plural|title }}{% endblock box_title %}
{% block box_content %}
  {{ formset.formset.management_form }}
  {{ formset.formset.non_form_errors }}
  {% crispy formset.formset.0 formset.formset.helper %}
{% endblock box_content %}
