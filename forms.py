from flask_wtf import Form
from wtforms import (StringField, PasswordField, SelectField, DecimalField, 
					 SubmitField, TextAreaField, IntegerField, HiddenField,
					 FileField)
from wtforms.validators import (DataRequired, Regexp, ValidationError, Email,
								 Length, EqualTo, Optional, NumberRange, Required)

from flask_wtf.file import FileField, FileAllowed, FileRequired

from flask.ext.login import (LoginManager, login_user, logout_user,
							 login_required, current_user)
from flask.ext.bcrypt import check_password_hash

import models

def account_exists(form, field):
	if (models.User.get(models.User.id==current_user.id).accounts
				   .where(models.Account.name==field.data)
				   .exists()):
		raise ValidationError("Account already exists")

def name_exists(form, field):
	if models.User.select().where(models.User.username == field.data).exists():
		raise ValidationError("Username already exists")

def email_exists(form, field):
	if models.User.select().where(models.User.email == field.data).exists():
		raise ValidationError("Email already exists")

def invalid_login(form, field):
	
	try:
		user = models.User.get(models.User.email == form.email.data)

		if check_password_hash(user.password, form.password.data) == False:
			raise ValidationError('Email or password does not match')
	except models.DoesNotExist:
		raise ValidationError('Email or password does not match.')

def getuser():
	my_list = [('', '')]
	users = models.User.select()
	for user in users:
		my_list.append((user.id, user.username))
	return my_list

def getUnits():
	units = models.Unit.select()

	optimised_units = [(unit.id, unit.short_name) for unit in units]
	
	return optimised_units

class AddProductForm(Form):
	brand = StringField(
						'Brand',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 Length(max=140)			   			   				 
			])

	description = StringField(
						'Description',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 Length(max=140)			   			   				 
			])

	product = StringField(
						'Product',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 Length(max=255)			   			   				 
			])

	quantity = StringField(
						'Number',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 Length(max=20)			   			   				 
			])

	units = SelectField('Units', coerce=int,
							 choices=getUnits(),
								validators=[Required()]
							)

	price = DecimalField(
						'Price',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 NumberRange(min=0, max=500)
			])

	target = IntegerField(
						'Target',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 NumberRange(min=0, max=20000)
			])

	moq = IntegerField(
						'MOQ',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 NumberRange(min=0, max=20000)
			])

	image = FileField('Image', validators=[
        FileRequired(),
        FileAllowed(['jpg', 'png'], 'Images only!')
    ])

class RegisterForm(Form):
	email = StringField(
						'Your Email',
			   			   validators = [
			   			   				 DataRequired(),
			   			   				 Email(),
			   			   				 email_exists
			])

	password = PasswordField(
							 'Password',
				   			 validators = [
				   			 				DataRequired(),
				   			   				Length(min=8),
				   			   				EqualTo('confirm_password', message='Passwords must match')
			   ])
			   
	confirm_password = PasswordField(
									 'Confirm Password',
									 validators = [
									 				DataRequired()
									 ]
						)
	
	phone = IntegerField(
			   			   'Contact Phone Number',
			   			   validators = [
			   			   					DataRequired(),
											NumberRange(min=263710000000, message='Invalid phone number. Correct format: 263712345678')
			   	])

	address = TextAreaField(
			   			   'Delivery Address',
			   			   validators = [
			   			   					DataRequired()
			   	])

class OrderForm(Form):
	quantity = IntegerField(
					'Order Quantity',
			   		validators = [
			   			DataRequired(),
			   			NumberRange(min=100, message='The Minimum Order Quantity (MOQ) is 100')
			   	])

class LoginForm(Form):
    email = StringField('Email', validators=[DataRequired(), Email(), invalid_login])
    password = PasswordField('Password', validators=[DataRequired(), invalid_login])
