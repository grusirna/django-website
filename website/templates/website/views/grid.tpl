{% extends base_template %}
{% load i18n %}

{% load website_tags %}

{% block extrastyle %}
    {{ block.super }}
    <style type="text/css">
        .btn-toolbar {
            margin-top: 0;
        }

        content-block.full-content {
            margin-left: 0;
        }
    </style>
{% endblock %}
{% block bodyclass %}change-list{% endblock %}

{% block nav_title %}
    {% if brand_icon %}<i class="{{ brand_icon }}"></i> {% endif %}{{ brand_name }}
{% endblock %}

{% if not adminlte %}
    {% block nav_toggles %}
        {% include "website/includes/toggle_menu.tpl" %}
        {% if has_add_permission %}
            <a href="{{ add_url }}" class="navbar-toggle pull-right"><i class="fa fa-plus"></i></a>
        {% endif %}
        <button class="navbar-toggle pull-right" data-toggle="collapse" data-target=".content-navbar .navbar-collapse">
            <i class="fa fa-filter"></i>
        </button>
    {% endblock %}
{% endif %}

{% block nav_btns %}
    {% if cl.pop %}
        <a href="#" id="confirm_select" class="btn btn-primary {% if cl.select_close %}select_close{% endif %}"><i
                class="fa fa-plus"></i> 确认选择</a>
    {% else %}
        {% if has_add_permission %}
            <a href="{{ add_url }}" class="btn btn-primary"><i class="fa fa-plus"></i>
                新增</a>
        {% endif %}
        {{ nav_buttons }}
    {% endif %}
{% endblock nav_btns %}

{% block nav_middle %}
    {% plugin_block 'results_bottom' %}
{% endblock %}

{% block nav_form %}

    <div class="btn-toolbar pull-right clearfix">
        {% plugin_block 'top_toolbar' %}

        {% if cl.col_ctrl %}
            <div class="btn-group" title="可见字段">
                <a class="dropdown-toggle btn btn-default btn-sm" data-toggle="dropdown" href="#">
                    <i class="fa fa-exchange"></i> </span>
                </a>
                <ul class="dropdown-menu model_fields pull-right" role="menu" aria-labelledby="dLabel">
                    <li><a href="{{ clean_select_field_url }}"><i class="fa fa-refresh"></i> 重置</a></li>
                    <li class="divider"></li>
                    {% for f, selected, flink in model_fields %}
                        <li><a href="{{ flink }}">
                            {% if selected %}<i class="fa fa-check"></i>{% else %}<i class="fa fa-blank"></i>{% endif %}
                            {{ f.verbose_name }}</a></li>
                    {% endfor %}
                </ul>
            </div>
        {% endif %}

    </div>
{% endblock %}

{% block content %}
    {% ifequal cl.filter_list_position 'left' %}
        <div class="row">
        <div class="col-md-2">
            {% plugin_block 'grid_left' %}
        </div>
        <div class="col-md-10">
    {% endifequal %}
{% if cl.list_tabs %}
    <div class="nav-tabs-custom">
    <ul class="nav nav-tabs">
        {% for tab_url,tab_title in cl.list_tabs %}
            <li class="{% ifequal cur_tab forloop.counter0 %}active{% endifequal %}"><a
                    href="{{ tab_url }}&_tab={{ forloop.counter0 }}">{{ tab_title }}</a></li>
        {% endfor %}
    </ul>
{% endif %}
<form id="changelist-form" action="" method="post" {% plugin_block 'result_list_form' %}>{% csrf_token %}
    {% plugin_block 'results_top' %}
    <div class="results table-responsive no-padding">

        {% ifequal cl.filter_list_position 'top' %}
            <div class=" btn-group">
                {% plugin_block 'grid_top' %}
            </div>
        {% endifequal %}

        {% if results %}
            {% block results_grid %}
                <table class="table table-hover">
                    {% block results_grid_head %}
                        <thead>
                        <tr>{% for o in result_headers.cells %}
                            <th {{ o.tagattrs }}>
                                {% if o.btns %}
                                    <div class="pull-right">
                                        {% for b in o.btns %}
                                            {{ b|safe }}
                                        {% endfor %}
                                    </div>
                                {% endif %}
                                {% if o.menus %}
                                    <div class="dropdown pull-left">
                                        <a class="dropdown-toggle" data-toggle="dropdown" href="#">
                                            {{ o.label }}
                                        </a>
                                        <ul class="dropdown-menu" role="menu">
                                            {% for m in o.menus %}
                                                {{ m|safe }}
                                            {% endfor %}
                                        </ul>
                                    </div>
                                {% else %}
                                    {{ o.label }}
                                {% endif %}
                            </th>{% endfor %}
                        </tr>
                        {% plugin_block 'result_head' %}
                        </thead>
                    {% endblock results_grid_head %}
                    {% block results_grid_body %}
                        <tbody>
                        {% for row in results %}
                            <tr class="grid-item{% if row.css_class %} {{ row.css_class }}{% endif %}">
                                {% for c in row.cells %}
                                    <td {{ c.tagattrs }}>
                                        {% if c.btns %}
                                            <div class="btn-group pull-right">
                                                {% for b in c.btns %}
                                                    {{ b|safe }}
                                                {% endfor %}
                                            </div>
                                        {% endif %}
                                        {% if c.menus %}
                                            <div class="dropdown">
                                                <a class="dropdown-toggle" data-toggle="dropdown" href="#">
                                                    <div style="white-space: pre">{{ c.label }}</div>

                                                </a>
                                                <ul class="dropdown-menu">
                                                    {% for m in c.menus %}
                                                        {{ m|safe }}
                                                    {% endfor %}
                                                </ul>
                                            </div>
                                        {% else %}
                                            <div style="white-space: pre">{{ c.label }}</div>
                                        {% endif %}
                                    </td>
                                {% endfor %}</tr>
                            {% plugin_block 'result_row' row %}
                        {% endfor %}
                        </tbody>
                    {% endblock results_grid_body %}
                </table>
            {% endblock results_grid %}
        {% else %}
            {#            <p class="well">无数据</p>#}
            <p class="well">{% firstof cl.no_data_tips '无数据' %}</p>
        {% endif %}
    </div>

    <input type="hidden" id="action" name="action" value=""/>
    <input type="hidden" id="select-across" name="select_across" value=""/>

    {% if not adminlte %}
        <div class="form-actions well well-sm">
            {% plugin_block 'results_bottom' %}
        </div>
    {% endif %}
</form>

{% if adminlte %}
    <div class="box-footer">
        <ul class="pagination pagination-sm no-margin pull-right">
            {% plugin_block 'pagination' 'small' %}
        </ul>
    </div>
    </div>

{% else %}
    <ul class="pagination">
        {% plugin_block 'pagination' %}
    </ul>
{% endif %}

{% if cl.list_tabs %}
    </div>
{% endif %}


{% ifequal cl.filter_list_position 'left' %}
    </div>
    </div>
{% endifequal %}

{% endblock %}
