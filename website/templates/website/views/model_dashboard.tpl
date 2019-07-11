{% extends 'website/views/dashboard.tpl' %}
{% load i18n website_tags %}


{% block breadcrumbs %}
<ul class="breadcrumb">
  <li><a href="{% url website|website_namespace:'index' %}">{% trans 'Home' %}</a></li>
  <li>
    <a href="{% url opts|admin_urlname:'changelist'|append_namespace:website %}">{{ opts.verbose_name_plural|capfirst }}</a>
  </li>
  <li class="active">
    {{ object|truncatewords:"18" }}
  </li>
</ul>
{% endblock %}

{% block nav_toggles %}
{% include "website/includes/toggle_back.tpl" %}
{% if has_change_permission %}
  <a href="{% url opts|admin_urlname:'change' object.pk|append_namespace:website %}" class="navbar-toggle pull-right"><i class="fa fa-pencil"></i></a>
{% endif %}
{% endblock %}

{% block nav_btns %}
  {% if has_change_permission %}
  <a href="{% url opts|admin_urlname:'change' object.pk|append_namespace:website %}" class="btn btn-primary"><i class="fa fa-pencil"></i> <span>{% trans "Edit" %}</span></a>
  {% endif %}
{% endblock %}
