{% extends "website/edit_inline/base.tpl" %}
{% load i18n website_tags crispy_forms_tags %}

{% block box_content_class %}formset-content{% endblock box_content_class %}
{% block box_content %}<p class="text-muted">{% trans "Null" %}</p>{% endblock box_content %}
