{% extends 'website/base.tpl' %}
{% load i18n website_tags %}

{% block title %}{{ title }} | {{ site_title }}{% endblock %}

{% if head_fix %}
    {% block extrastyle %}
        <style type='text/css'>
            body {
                background-color: #ecf0f5;
            }
        </style>
    {% endblock %}
{% endif %}

{% block body %}
    <div {% if not head_fix %}class="wrapper"{% endif %}>

        <!-- Header -->
        {% if not head_fix %}
            {% include 'website/includes/adminlte.head_nav.tpl' %}
        {% endif %}


        <!-- left side menu -->
        {% block left_menu %}
            {% if not head_fix %}
                <aside class="main-sidebar">
                    <section style="height: auto;" class="sidebar">
                        {% block navbar %}
                            {% if nav_menu %}
                                {% include menu_template %}
                            {% else %}
                                <p></p>
                            {% endif %}
                        {% endblock %}
                        {% plugin_block 'left_navbar' %}
                    </section>
                </aside>
            {% endif %}
        {% endblock %}

        <div id="content-block" class="{% if not head_fix %}content-wrapper{% else %}{% endif %}">


            <section class="content-header">
                <h1 class="text-of">
                    {% if title %}{{ title }}{% endif %}
                    {% if subtitle %}
                        <small>{{ subtitle }}</small>{% endif %}
                </h1>
            </section>

            <section class="content">

                <!-- messages -->
                {% block messages %}
                    {% if messages %}
                        {% for message in messages %}
                            <div class="alert alert-dismissable{% if message.tags %} {% if message.tags == 'error' %}alert-danger{% else %}alert-{{ message.tags }}{% endif %}{% endif %}">
                                <button type="button" class="close" data-dismiss="alert">&times;</button>
                                {{ message }}
                            </div>
                        {% endfor %}
                    {% endif %}
                {% endblock messages %}
                {% block boxs %}
                    <div class="box box-solid">
                        <div class="box-header">
                            <!-- content nav -->
                            {% block content-nav %}
                                <div class="row">
                                    <!-- 创建等动作 -->
                                    <div class="col-sm-4">
                                        {% plugin_block 'nav_btns' %}
                                        {% block nav_btns %}{% endblock %}
                                        {% block nav_middle %}{% endblock %}
                                    </div>
                                    <div class="col-sm-4">
                                        <!-- 过滤器 -->
                                        <div>
                                            {% plugin_block 'nav_menu' %}
                                        </div>
                                    </div>
                                    <div class="col-sm-4">
                                        {% plugin_block 'nav_form' %}
                                    </div>
                                </div>
                                <div class="row">
                                    <div class="col-sm-12">
                                        {% block nav_form %}{% endblock %}
                                    </div>
                                </div>
                            {% endblock %}
                        </div>
                        {% block content %}

                            <div class="box-body">
                                <!-- content -->
                                {{ content }}
                            </div>
                        {% endblock %}

                    </div>

                {% endblock %}
            </section>
        </div>


    </div>
{% endblock body %}
