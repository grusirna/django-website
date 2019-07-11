{% load i18n website_tags %}


{% block navbar_md %}
<ul class="sidebar-menu tree" data-widget="tree">
    <!--<li class="treeview">-->
    <!--<a class="section" href="{% url website|website_namespace:'index' %}"><i class="icon fa-fw fa fa-home"></i>-->
    <!--<span>概况</span></a>-->
    <!--</li>-->
    {% for leaf in nav_menu.leaf %}
    <li class="treeview {% if leaf.selected %} active{% endif %}">
        <a class="section" href="{{ leaf.url}}">
            <i class="icon fa-fw fa {{ leaf.icon}}"></i>
            <span>{{ leaf.title}}</span></a>
        </a>

    </li>
    {% endfor %}

    {% for item in nav_menu.branch %}
    <li class="treeview  {% if item.data.selected %} active{% endif %}">
        <a href="{{item.data.url}}" class="section">
            {% if item.data.icon %}<i class="fa fa-fw {{ item.data.icon }}"></i>
            {% elif item.data.first_icon %}<i class="fa fa-fw {{ item.data.first_icon }}"></i>
            {% else %}<i class="fa fa-fw fa-circle-o"></i>{% endif %}
            <span>{{ item.data.title }}</span>
            <span class="pull-right-container">
              <i class="fa fa-angle-left pull-right"></i>
            </span>
        </a>

        <ul class="treeview-menu">
            {% for leaf in item.leaf %}
            <li {% if leaf.selected %}class="active" {% endif %}><a href="{{ leaf.url}}"><i class="fa {{ leaf.icon}}"></i> {{leaf.title}}</a></li>
            {% endfor %}
            {% for item in item.branch %}
            <li {% if item.data.selected %}class="active" {% endif %}>
                <a href="{{item.data.url}}" class="section">
                    {% if item.data.icon %}<i class="fa fa-fw {{ item.data.icon }}"></i>
                    {% elif item.data.first_icon %}<i class="fa fa-fw {{ item.data.first_icon }}"></i>
                    {% else %}<i class="fa fa-fw fa-circle-o"></i>{% endif %}
                    <span>{{ item.data.title }}</span> <span class="pull-right-container">
              <i class="fa fa-angle-left pull-right"></i>
            </span>
                </a>
                <ul class="treeview-menu  ">
                    {% for leaf in item.leaf %}
                    <li {% if leaf.selected %}class="active" {% endif %}><a href="{{ leaf.url}}"><i class="fa {{ leaf.icon}}"></i> {{leaf.title}}</a></li>
                    {% endfor %}

                </ul>
            </li>
            {% endfor %}


        </ul>

    </li>
    {% endfor %}


    {% plugin_block 'menu-nav' %}
</ul>
{% endblock navbar_md %}


