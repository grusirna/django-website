{% extends "website/index.tpl" %}
{% load i18n %}


{% if not is_popup %}
{% block breadcrumbs %}
<ul class="breadcrumb">
  <li>
    <a href="{% url website|website_namespace:'index' %}">{% trans 'Home' %}</a>
  </li>
{% for app in app_list %}
  <li class="active">
    <span>{% blocktrans with app.name as name %}{{ name }}{% endblocktrans %}</span>
  </li>
{% endfor %}
</ul>
{% endblock %}
{% endif %}

{% block sidebar %}{% endblock %}
