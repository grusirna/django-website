{% load website_tags %}
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