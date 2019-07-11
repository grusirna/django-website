{% load i18n %}
<li class="dropdown btn-group">
    <a id="drop-bookmark" title="{{ bk_menu_title }}" class="dropdown-toggle btn" role="button" data-toggle="dropdown"
       href="#">
        <i class="fa fa-book"></i> {{ bk_menu_title|truncatechars:9 }}<span class="caret"></span></a>
    <ul id="bookmark-menu" class="dropdown-menu" role="menu">
        {% if bk_has_selected %}
            <li><a href="{{ bk_list_base_url }}"><i class="fa fa-blank"></i> 清除视图</a></li>
            <li class="divider"></li>
        {% endif %}
        {% for bk in bk_viewmarks %}
            <li class="{% if bk.selected %}active {% endif %}{% if bk.edit_url %}with_menu_btn{% endif %}">
                <a href="{{ bk.url }}" title="{{ bk.title }}"><i class="fa fa-bookmark"></i> {{ bk.title }}</a>
                {% if bk.edit_url and has_change_permission_viewmark %}
                    <a href="{{ bk.edit_url }}" class="dropdown-menu-btn"><i class="fa fa-pencil"></i></a>
                {% endif %}
            </li>
        {% empty %}
            <li><a class="mute">没有视图</a></li>
        {% endfor %}
        {% if not bk_has_selected and bk_current_qs and has_add_permission_viewmark %}
            <li class="divider add-bookmark"></li>
            <li class="dropdown-submenu add-bookmark"><a href="#"><i class="fa fa-plus"></i> 新建视图
            </a>
                <div class="popover right dropdown-menu">
                    <div class="arrow"></div>
                    <h3 class="popover-title">
                        保存当前视图
                    </h3>
                    <div class="popover-content">
                        <form id="bookmark_form" method="post" action="{{ bk_post_url }}">
                            {% csrf_token %}
                            <input type="hidden" name="query" value="{{ bk_current_qs }}"/>
                            <input name="title" type="text" class="form-control"
                                   placeholder="输入视图标题…"/>
                            <button class="btn btn-success" type="submit"
                                    data-loading-text="{% trans "Waiting" %}...">保存视图</button>
                        </form>
                    </div>
                </div>
            </li>
        {% endif %}
    </ul>
</li>
