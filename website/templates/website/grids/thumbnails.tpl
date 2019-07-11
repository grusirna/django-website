{% extends "website/views/grid.tpl" %}

{% block toolbar_layouts %}{% endblock toolbar_layouts %}
{% block results_grid_body %}{% endblock results_grid_body %}
{% block results_grid_head %}{% endblock results_grid_head %}

{% block results_grid %}
    {{ block.super }}
    <div class="panel panel-default thumbnail-panel">
        <div class="panel-body">
            <div class="row">
                {% for obj in results %}
                    {% block grid_item %}
                        <div class="col-md-2 col-sm-3 col-xs-4">
                            <div class="thumbnail text-center grid-item">


                                <ul class="list-unstyled" style="line-height: 25px;">
                                    {% if obj.thumbnail_label %}
                                        {{ obj.thumbnail_label.label }}
                                    {% endif %}
                                    {% for o in obj.cells %}
                                        {% if not o.thumbnail_hidden %}
                                            <li class="text-left">
                                                {% if o.btns %}
                                                    <div class="btn-group pull-right">
                                                        {% for b in o.btns %}
                                                            {{ b|safe }}
                                                        {% endfor %}
                                                    </div>
                                                {% endif %}

                                                {% if o.menus %}
                                                    <div class="dropdown">
                                                        <a class="dropdown-toggle" data-toggle="dropdown" href="#">
                                                            {{ o.label }}
                                                        </a>
                                                        <ul class="dropdown-menu">
                                                            {% for m in o.menus %}
                                                                {{ m|safe }}
                                                            {% endfor %}
                                                        </ul>
                                                    </div>
                                                {% else %}
                                                    {{ o.label }}
                                                {% endif %}
                                            </li>{% endif %}
                                    {% endfor %}
                                </ul>
                            </div>
                        </div>
                    {% endblock grid_item %}
                {% endfor %}
            </div>
        </div>
    </div>
{% endblock results_grid %}
