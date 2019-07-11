{% extends "website/views/model_form.tpl" %}
{% load i18n %}

{% load website_tags %}

{% block breadcrumbs %}
<ul class="breadcrumb">
  <li><a href="{% url website|website_namespace:'index' %}">{% trans 'Home' %}</a></li>
  <li><a href="{% url opts|admin_urlname:'changelist'|append_namespace:website %}">{{opts.verbose_name_plural|capfirst}}</a></li>
  <li><a href="{% url opts|admin_urlname:'change' object.pk |append_namespace:website%}">{{ object|truncatewords:"18" }}</a></li>
  <li><a href="{% url opts|admin_urlname:'revisionlist' object.pk|append_namespace:website %}">{% trans 'History' %}</a></li>
  <li class="active">{% blocktrans with opts.verbose_name as verbose_name %}Diff {{verbose_name}}{% endblocktrans %}</li>
</ul>
{% endblock %}

{% block nav_title %}
  <i class="fa fa-time"></i> {% blocktrans with opts.verbose_name as verbose_name %}Diff {{verbose_name}}{% endblocktrans %}
{% endblock %}

{% block content %}
<div class="module">
  <table id="change-diff" class="table table-bordered table-hover">
    <thead>
      <tr>
        <th scope="col">{% trans 'Field' %}</th>
        <th scope="col">{% trans 'Version A' %}</th>
        <th scope="col">{% trans 'Version B' %}</th>
      </tr>
    </thead>
    <tbody>
      {% for label, value_a, value_b, diff in diffs %}
        <tr{%if diff%} class="diff-row warning"{% endif %}>
          <th scope="row">{{ label }}</th>
          <td class="version-a{%if not diff%} text-muted{% endif %}">{{value_a}}</td>
          <td class="version-b{%if not diff%} text-muted{% endif %}">{{value_b}}</td>
        </tr>
      {% endfor %}
        <tr>
          <th scope="row">{% trans "Revert to" %}</th>
          <td><a class="btn btn-default" href="{{revision_a_url}}"><i class="fa fa-undo"></i> {% trans 'Revert' %}</a></td>
          <td><a class="btn btn-default" href="{{revision_b_url}}"><i class="fa fa-undo"></i> {% trans 'Revert' %}</a></td>
        </tr>
    </tbody>
  </table>
</div>
{% endblock %}
