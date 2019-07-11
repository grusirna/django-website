{% load website_tags %}{% load i18n %}<!DOCTYPE html>
<html lang="zh_CN">
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {# 额外的meta#}
    {% block extrameta %}
        <meta name="description" content=""/>
        <meta name="author" content=""/>
    {% endblock %}
    {#蜘蛛选项#}
    {% block blockbots %}
        <meta name="robots" content="NONE,NOARCHIVE"/>{% endblock %}
    {#标题#}
    <title>{% block title %}{% endblock %}</title>
    {#bootstrap.css等基础vendor#}
    {% vendor 'bootstrap.css' 'font-awesome.css' %}
    {% vendor 'website.main.css' 'website.plugins.css' 'website.responsive.css' %}

    {#站点皮肤#}
    {% if site_theme %}
        <link rel="stylesheet" type="text/css" id="site-theme" href="{{ site_theme }}"/>
    {% else %}
        <link rel="stylesheet" type="text/css" id="site-theme"
              href="{% static "website/css/themes/bootstrap-website.css" %}"/>
    {% endif %}

    {#adminlte css#}
    {% if adminlte %}
        <link rel="stylesheet" type="text/css" href="{% static "website/vendor/adminlte/dist/css/AdminLTE.css" %}"/>
        <link rel="stylesheet" type="text/css"
              href="{% static "website/vendor/adminlte/dist/css/skins/_all-skins.min.css" %}"/>
        <link rel="stylesheet" type="text/css" href="{% static "website/css/website.adminlte.custom.css" %}"/>
    {% endif %}

    {#iframe样式#}
    {% if head_fix %}
        <link href="{% static "website/css/website.main.frame.css" %}" rel="stylesheet">
    {% endif %}

    {#view.get_media获取的css集合#}
    {{ media.css }}
    {#额外的style#}
    {% block extrastyle %}{% endblock %}

    {% url website|website_namespace:'index' as indexurl %}

    <script type="text/javascript">
        window.__admin_media_prefix__ = "{% filter escapejs %}{% static "website/" %}{% endfilter %}";
        window.__admin_path_prefix__ = "{% filter escapejs %}{{ indexurl }}{% endfilter %}";
    </script>

    {#iframe js config#}
    {% block headfix %}
        {% if head_fix %}
            <script type="text/javascript" src="{% static "website/js/site_config.js" %}"></script>
        {% endif %}
    {% endblock %}
    <script src="{% static "website/vendor/pace/pace.min.js" %}"></script>
    <style>
        .pace {
            -webkit-pointer-events: none;
            pointer-events: none;

            -webkit-user-select: none;
            -moz-user-select: none;
            user-select: none;
        }

        .pace-inactive {
            display: none;
        }

        .pace .pace-progress {
            background: #4130dd;
            position: fixed;
            z-index: 2000;
            top: 0;
            right: 100%;
            width: 100%;
            height: 2px;
        }


    </style>
    {% block extrahead %}{% endblock %}
    {% plugin_block 'extrahead' %}

</head>
{#adminlte、bodyclass#}
<body class="


        {% if adminlte %}{% block basebodyclass %}skin-blue  sidebar-mini{% endblock %} {% endif %}{% block bodyclass %}{% endblock %}">
{#body#}
{% block body %}{% endblock body %}
{#js翻译#}
<script type="text/javascript" src="{% url website|website_namespace:'jsi18n' %}"></script>
{#基础js库#}

{% vendor 'jquery.js' 'bootstrap.js' %}
{% vendor 'jquery-ui-sortable.js' 'website.main.js' 'website.responsive.js' %}
{#adminlte js#}
{% if adminlte %}
    <script src="{% static "website/vendor/adminlte/dist/js/app.min.js" %}"></script>
    <script src="{% static "website/vendor/adminlte/dist/js/setup.js" %}"></script>
    <script src="{% static "website/vendor/adminlte/plugins/slimscroll/jquery.slimscroll.min.js" %}"></script>
{% endif %}
{#view.get_media获取的js集合#}
{{ media.js }}
{#template继承额外body#}
{% block extrabody %}{% endblock %}
{#插件实现body#}
{% plugin_block 'extrabody' %}
</body>
</html>
