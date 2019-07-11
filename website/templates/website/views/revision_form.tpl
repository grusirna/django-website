{% extends "website/views/model_form.tpl" %}
{% load i18n %}

{% load website_tags %}

{% block breadcrumbs %}
<ul class="breadcrumb">
  <li><a href="{% url website|website_namespace:'index' %}">{% trans 'Home' %}</a></li>
  <li>
    {% if has_view_permission %}
    <a href="{% url opts|admin_urlname:'changelist'|append_namespace:website %}">{{ opts.verbose_name_plural|capfirst }}</a>
    {% else %}{{ opts.verbose_name_plural|capfirst }}{% endif %}
  </li>
  <li><a href="{% url opts|admin_urlname:'change' object.pk|append_namespace:website %}">{{ object|truncatewords:"18" }}</a></li>
  <li><a href="{% url opts|admin_urlname:'revisionlist' object.pk|append_namespace:website %}">{% trans 'History' %}</a></li>
  <li class="active">{% blocktrans with opts.verbose_name as verbose_name %}Revert {{verbose_name}}{% endblocktrans %}</li>
</ul>
{% endblock %}

{% block content %}
    <div class="alert alert-info">{% blocktrans %}Press the revert button below to revert to this version of the object.{% endblocktrans %}</div>
    {{block.super}}
{% endblock %}

{% block submit_buttons_bottom %}
<div class="form-actions well well-sm">
    <button type="submit" class="default btn btn-primary"><i class="fa fa-undo"></i> {% trans 'Revert this revision' %}</button>
</div>
{% endblock %}
