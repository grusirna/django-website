{% extends base_template %}
{% load i18n %}

{% load website_tags %}
{% load crispy_forms_tags %}

{% block bodyclass %}{{ opts.app_label }}-{{ opts.object_name.lower }} detail{% endblock %}

{% block nav_title %}
    {% if menu_icon %}<i class="{{ menu_icon }}"></i> {% endif %}{{ object|truncatewords:"18" }}
{% endblock %}

{% block nav_toggles %}
    {% include "website/includes/toggle_back.tpl" %}
    {% if has_change_permission %}
        <a href="{% url opts|admin_urlname:'change'|append_namespace:website object.pk %}" class="navbar-toggle pull-right"><i
                class="fa fa-pencil"></i></a>
    {% endif %}
    {% if has_delete_permission %}
        <a href="{% url opts|admin_urlname:'delete'|append_namespace:website object.pk %}" class="navbar-toggle pull-right"><i
                class="fa fa-trash-o"></i></a>
    {% endif %}
{% endblock %}

{% block nav_btns %}
    {% if has_change_permission %}
        <a href="{% url opts|admin_urlname:'change'|append_namespace:website object.pk %}" class="btn btn-primary"><i class="fa fa-pencil"></i>
            <span>{% trans "Edit" %}</span></a>
    {% endif %}
    {% if has_delete_permission %}
        <a href="{% url opts|admin_urlname:'delete'|append_namespace:website object.pk %}" class="btn btn-danger"><i class="fa fa-trash-o"></i>
            <span>{% trans "Delete" %}</span></a>
    {% endif %}
{% endblock %}

{% block content %}
    {% plugin_block 'before_fieldsets' %}
    {% crispy form %}
    {% plugin_block 'after_fieldsets' %}
{% endblock %}
