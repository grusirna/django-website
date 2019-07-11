{% extends 'website/base.tpl' %}
{% load i18n website_tags %}


{% block title %}{{ title }} | {{ site_title }}{% endblock %}

{% block extrastyle %}

    <style type="text/css">
        #sap-container {
            position: relative;
            width: 100%;
            height: 100%;
        }

        #sap-container iframe {
            display: block;
            width: 100%;
            height: 100%;
            border: none;
        }
    </style>

{% endblock %}

{% block body %}
    <div class="wrapper">

        <!-- Header -->
        {% include 'website/includes/adminlte.head_nav.tpl' %}


        <!-- left side menu -->
        {% block left_menu %}
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
        {% endblock %}

        <div id="content-block" class="content-wrapper">

            <!-- 右侧iframe展示区域  -->
            <div id="sap-container">
            </div>

        </div>


    </div>
{% endblock body %}


{% block extrabody %}
    <script src="{% static "website/vendor/inspinia/js/plugins/slimscroll/jquery.slimscroll.min.js" %}"></script>
    <script src="{% static "website/js/iframer.js" %}"></script>

    <script>

        $(document).ready(function () {
            $(".sidebar-menu a").on("click", function () {
                var to = $(this).attr("href");
                if (to.length > 1) {
                    iframer.jumpTo(to);
                    return false;
                }
            });

            function fix_height() {
                var h = $(window).height() - 52 + "px";
                //$('#content-block').css("height", h);
                $('#sap-container').css("height", h);
                //$('#sap-container iframe').contents().find("#content-block").css("min-height",h);
            }

            fix_height();

            $(window).bind("load resize scroll", function () {
                fix_height();
            });

        });

        iframer.init({
            //存放iframe的容器
            container: document.getElementById('sap-container'),
            expect_class: 'spa-expect-links',
        });
    </script>
{% endblock %}
