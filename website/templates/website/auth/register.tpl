{% extends base_template %}
{% load i18n website_tags %}

{% load crispy_forms_tags %}

{% block title %}{{ title }}{% endblock %}
{% block basebodyclass %}hold-transition register-page{% endblock %}
{% block body %}
    <div class="register-box">
        <div class="register-logo">
            <a href="{% url 'service:index' %}"><b>{{ site_title }}</b></a>
        </div>

        <div class="register-box-body">
            <p class="login-box-msg">注册一个新的账号</p>
            {#form#}
            <form  method="post" id="register-form">
                <div class="form-group has-feedback">
                    <input type="text" class="form-control" placeholder="Full name">
                    <span class="glyphicon glyphicon-user form-control-feedback"></span>
                </div>
                <div class="form-group has-feedback">
                    <input type="email" class="form-control" placeholder="Email">
                    <span class="glyphicon glyphicon-envelope form-control-feedback"></span>
                </div>
                <div class="form-group has-feedback">
                    <input type="password" class="form-control" placeholder="Password">
                    <span class="glyphicon glyphicon-lock form-control-feedback"></span>
                </div>
                <div class="form-group has-feedback">
                    <input type="password" class="form-control" placeholder="Retype password">
                    <span class="glyphicon glyphicon-log-in form-control-feedback"></span>
                </div>
                <div class="row">
                    <div class="col-xs-8">
                        <div class="checkbox icheck">
                        </div>
                    </div>
                    <!-- /.col -->
                    <div class="col-xs-4">
                        <button type="submit" class="btn btn-primary btn-block btn-flat">注册</button>
                    </div>
                    <!-- /.col -->
                </div>
            </form>

            <a href="{% url 'service:index' %}" class="text-center">我有一个已经存在的账号</a>
        </div>
        <!-- /.form-box -->
    </div>
    <!-- /.register-box -->

{% endblock %}
