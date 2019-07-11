{% extends base_template %}
{% load i18n %}

{% load website_tags %}
{% load crispy_forms_tags %}

{% block bodyclass %}{{ opts.app_label }}-{{ opts.object_name.lower }} change-form{% endblock %}

{% block nav_title %}{% if menu_icon %}
    <i class="{{ menu_icon }}"><sub class="fa fa-{% if add %}plus{% else %}pencil{% endif %}"></sub></i> {% endif %}
    {{ title }}{% endblock %}


{% block nav_middle %}
    {% if change %}
        <form id="changelist-form" action="{% url opts|admin_urlname:'changelist'|append_namespace:website %}" method="post">{% csrf_token %}
            <input name="_selected_action" type="hidden" value="{{ original.pk }}"/>
            <input type="hidden" id="action" name="action" value=""/>
            {% plugin_block 'results_bottom' %}

        </form>
    {% endif %}
{% endblock %}

{% block nav_btns %}
    {% include "website/includes/form_btn.tpl" %}
    {% if change and cl.log %}
        <a href="{% url website|website_namespace:'index' %}website/logentry/?_p_content_type={{ content_type_id }}&_p_object_id={{ original.pk }}"
           class="btn"><i class="fa fa-eye"></i> 历史</a>
    {% endif %}
{% endblock nav_btns %}

{% block content %}
    <form class="exform" onsubmit="$.do_submit()"
          {% if has_file_field %}enctype="multipart/form-data" {% endif %}action="{{ form_url }}" method="post"
          id="{{ opts.module_name }}_form">{% csrf_token %}
        {% block form_top %}{% endblock %}
        {% plugin_block 'form_top' %}

        {% if errors %}
            <div class="alert alert-danger alert-dismissable">
                <button type="button" class="close" data-dismiss="alert">&times;</button>
                {% blocktrans count counter=errors|length %}Please correct the error below.{% plural %}Please correct
                    the errors below.{% endblocktrans %}
            </div>
            {{ form.non_field_errors }}
        {% endif %}

        {% plugin_block 'before_fieldsets' %}

        {% crispy form %}

        {% plugin_block 'after_fieldsets' %}

        {% block submit_buttons_bottom %}{% include "website/includes/submit_line.tpl" %}{% endblock %}
    </form>


{% endblock %}
