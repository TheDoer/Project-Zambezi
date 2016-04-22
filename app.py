import json, os, datetime, io
from random import randint
from urllib.parse import urlparse

import requests, http, pycurl

from werkzeug import secure_filename
from flask import Flask, render_template, session, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from flask.ext.bcrypt import generate_password_hash
from flask.ext.socketio import SocketIO, emit
from urllib.parse import urlencode

from models import *
from pagination import Pagination

import forms

# import libraries for socketing
import socket
import sys
from threading import *


DEBUG = True
PORT = ''
HOST = 'roundshopper.com'
#HOST = 'localhost'
UPLOAD_FOLDER = '/home/androunditgoes/mysite/static/img/'
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])
PER_PAGE = 5

app = Flask(__name__)
app.secret_key = 'mlskdjfisfwe[e20220i42mf2fra/aioh30mowgf0924mo2=gmvdVsv72v5v2vwvs5f3wef3wf83gf3v5esf1f3fw4vwvopw3mviosvmwpvp3ma31334ivlkwvog'
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

host, port = urlparse(os.environ["http_proxy"]).netloc.split(":")

def allowed_file(filename):
        return '.' in filename and \
               filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(userid):
	return User.get(User.id==userid)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

def send_sms(phone_number, message):
	# message may be string or dict
	if type(message) == dict:
		message = message['response']
	url = 'http://api.infobip.com'
	payload = {"to":"' + phone_number + '","text":"' + message + '"}
	headers = [
	    'authorization: Basic Um91bmRTaG9wcGVyOlJTaG9wcGVyMDQxNA==',
	    'content-type: application/json',
	    'accept: application/json'
	    ]

	storage = io.StringIO()
	c = pycurl.Curl()
	c.setopt(c.URL, url)

	postfields = urlencode(payload)

	c.setopt(c.POSTFIELDS, postfields)
	c.setopt(pycurl.HTTPHEADER, headers)

	c.perform()
	c.close()

	return storage.getvalue()

# def send_sms(phone_number, message):
	# if type(message) == dict:
	# 	message = message['response']

# 	return '{}: {}'.format(phone_number, message)

def stock_item_exists(order_no):
	'''This function checks if the stock item translated to by the order number exists.
	 If it does, the stock item is returned, if it doesn\'t, False is returned'''
	# check if order_no is valid and stock item exists
	try:
		catalogue_entry = Catalogue.get(Catalogue.short_code==order_no)

		# attempt to get stock item from catalogue entry
		# parameters holds the values needed to identify ordered stock item
		pars = catalogue_entry.long_code.split('R')

		stock_item = Stock.get(
			Stock.product==int(pars[0]),
			Stock.first_description==int(pars[1]),
			Stock.unit==int(pars[2]),
			Stock.brand==int(pars[3]),
			Stock.quantity==int(pars[4]),
			Stock.supplier==int(pars[5])
			)

		# return stock item
		return stock_item
	except DoesNotExist:
		return False

def process_order(quantity, stock):
	'''this function processes all incoming orders and returns a success or error response'''
	# current refers to the current number of orders
	# needed refers to the number of orders required to meet the target
	# target refers to the numbers of orders we have to reach before we can make an actual sale
	quantity = int(quantity)

	try:
		current = Order.select(fn.sum(Order.quantity)).where(Order.stock==stock.id).scalar() #Get the current number of orders

		if current == None: #I don't want a TypeError below
			current = 0

		needed = stock.minimum_quantity - current

		# verify if quantity is less than or equal to the needed orders
		if quantity <= needed :
			# verify if quantity is greater the MOQ
			if quantity >= stock.moq or quantity == needed:
				# calculate the amount the buyer has to pay
				price = quantity * stock.price

				order = Order.make_order(buyer=current_user.id, stock=stock, quantity=quantity, price=price)
				response = {
					'response': 'Order successfully placed. Order No: RS{}'.format(order.id),
					'category': 'green'
				}

				# check if the target has been met
				if stock.minimum_quantity == Order.select(fn.sum(Order.quantity)).where(Order.stock==stock.id).scalar():
					#update stock item
					stock.bought = True
					stock.save()

					orders = Stock.get(Stock.id==stock.id).orders

					for order in orders:
						order.ready = True
						order.save()
						send_sms(str(order.buyer.phone), 'Target met! Your order: RS{} is ready for delivery'.format(order.id))

			else:
				response = {
					'response': 'Your order is less than the MOQ of {}'.format(stock.moq),
					'category': 'red'
				}
		else:
			response = {
				'response': 'Only {} units left for ordering.'.format(needed),
				'category': 'red'
			}


	except TypeError:
		response = {
				'response': 'Invalid quantity',
				'category': 'red'
			}

	return response

@login_required
@app.route('/monitoring')
def monitoring():
	if current_user.is_authenticated:
		if current_user.account_type == 'supplier':
			return render_template('monitoring.html', HOST=HOST, PORT=PORT)
		else:
			return render_template('404.html', Order=Order), 404
	else:
		return render_template('404.html'), 404

@app.route('/monitoring/stocks', methods=['POST', 'GET'])
def monitoring_stocks():
	json_response = [
		['Status', 'Current', 'Needed', 'Canceled', {'role': 'annotation'}]
	]

	stocks = Stock.select()

	for stock in stocks:
		response = enquire(stock.id)
		response = response.split('R')
		json_response.append(['{}{} {} {}'.format(stock.quantity, stock.unit.short_name, stock.brand.name, stock.product.name), int(response[1]), int(response[2]), stock.deleted_orders.count(), ''])

	return json.JSONEncoder().encode(json_response)

@app.route('/enquiry', methods=['POST', 'GET'])
def enquire(id=None):
	'''This function is for enquiring the status of a stock item. Returns the target
	, current numbers of orders, needed orders to meet target and the stock item\'s moq'''

	try:
		# id passed as arg to function overides stock_id passed as arg to url
		if id != None:
			stock_id = id
		else:
			stock_id = request.args.get('stock_id', None)

		stock = Stock.get(Stock.id==stock_id)

		target = stock.minimum_quantity
		moq = stock.moq
		current = Order.select(fn.sum(Order.quantity)).where(Order.stock==stock.id).scalar()

		if current == None:
			current = 0

		needed = target - current

		response = '{}R{}R{}R{}'.format(target, current, needed, moq)

		return response
	except DoesNotExist:
		return 'Error'

@app.route('/catalogue', methods=['POST', 'GET'])
def catalogue():
	stocks = Stock.select().where(Stock.bought==False)

	output = ''

	flash('Oops. Sorry this page took long to load.', 'red')

	for stock in stocks:
		product = stock.product
		description = stock.first_description
		unit = stock.unit
		brand = stock.brand
		quantity = stock.quantity
		supplier = stock.supplier

		long_code = '{}R{}R{}R{}R{}R{}'.format(product.id, description.id, unit.id, brand.id, quantity, supplier.id)
		try:
			catalogue_entry = Catalogue.create_entry(long_code=long_code, short_code=None, available=True)

			# generate short_code from created catalogue entry and assign it to the new catalogue entry
			short_code = 'RS{}{}'.format('0' * (4 - len(str(catalogue_entry.id))), catalogue_entry.id)
			catalogue_entry.short_code = short_code

			# update the newly created catalogue entry with the short code
			catalogue_entry.save()
		except IntegrityError: # catalogue entry already exists
			# check if it has a short code assigned to it
			catalogue_entry = Catalogue.get(Catalogue.long_code==long_code)

			if catalogue_entry.short_code != None:
				# generate short_code from created catalogue entry and assign it to the new catalogue entry
				short_code = 'RS{}{}'.format('0' * (4 - len(str(catalogue_entry.id))), catalogue_entry.id)
				catalogue_entry.short_code = short_code

				# update the catalogue entry with the short code
				catalogue_entry.save()

	return render_template('catalogue.html', stocks=stocks, list=list,
		Catalogue=Catalogue, Order=Order)

@app.route('/sms_order', methods=['POST', 'GET'])
def sms_order():
	'''This function handles orders made via SMS '''
	# get the sender's phone number and message from the url
	from_ = request.args.get('from', None)
	body = request.args.get('body', None)

	# check if user is registered
	if not User.select().where(User.phone==from_, User.account_type=='buyer').exists():
		response = 'Phone number is not registered'
		return send_sms(phone_number=from_, message=response)

	if body == None:
		response = 'Message received but not processed'

	# split the message body to keywords and provide appropriate response
	keywords = body.split('*')

	# if the message has two words, then first keyword should either be enquiry or cancel else error
	if len(keywords) == 2:
		# process enquiry operation
		if keywords[0].lower() == 'enquiry' or keywords[0].lower() == 'inquiry':
			order_no = keywords[1].upper()

			# check if stock item exists
			if stock_item_exists(order_no) == False:
				response = 'Stock item not found.'
			else:
				stock_item = stock_item_exists(order_no)

				status = enquire(stock_item.id).split('R')

				response = 'Target: {} Current: {} Needed: {} MOQ: {}'.format(status[0], status[1], status[2], status[3] )

		# process cancel order operation
		elif keywords[0].lower() == 'cancel':
			order_no = int(keywords[1].upper().lstrip('RS'))
			#import pdb; pdb.set_trace()
			# check if order exists for this buyer
			if Order.select().where((Order.id==order_no) & (Order.buyer==User.get(User.phone==int(from_)).id)).exists():
				order = Order.get(Order.id==order_no)
				# set datetime cancelled
				order.date_cancelled = datetime.datetime.now()
				order.save()

				# save cancelled order in another table before deleting
				DeletedOrder.add_new(**order.__dict__['_data'])
				Order.delete_instance(order)

				response = 'Order RS{} has been cancelled'.format(order_no)
			else:
				response = 'Order RS{} does not exist'.format(order_no)
		# return error
		else:
			response = 'Invalid operation'

	# if the message has 3 keywords then it's an order
	elif len(keywords) == 3:
		if keywords[0].lower() == 'order':

			order_no = keywords[1].upper()
			quantity = keywords[2]

			# check if stock item exists
			if stock_item_exists(order_no) == False:
				response = 'Stock item not found.'
			else:
				stock_item = stock_item_exists(order_no)

				# check if item is available, if yes make order if not abort order
				if not stock_item.bought:
					response = process_order(quantity=quantity, stock=stock_item)
				else:
					response = 'Stock item not found.'
		else:
			# return error
			response = 'invalid input'
	else:
		response = 'invalid operation'

	return send_sms(phone_number=from_, message=response)

@app.route('/register', methods=['POST', 'GET'])
def register():
	register_form = forms.RegisterForm()

	if register_form.validate_on_submit():
		User.create_user(
			username='unknown',
			email=register_form.email.data,
			password=register_form.password.data,
			address=register_form.address.data,
			account_type='buyer',
			phone=register_form.phone.data)

		user = User.get(User.email==register_form.email.data)

		login_user(user)

		if user.account_type == 'buyer':
			return redirect(url_for('buyer'))
		elif user.account_type == 'supplier':
			return redirect(url_for('supplier'))
		else:
			return redirect(url_for('shipping'))

	return render_template('register.html', form=register_form)

@app.route('/supplier-register', methods=['POST', 'GET'])
def supplier_register():
	try:
		email = dict(request.form.items())['email']
		password = dict(request.form.items())['password']
		address = dict(request.form.items())['address']
		account_type = dict(request.form.items())['account_type']
		code = dict(request.form.items())['code']
		phone = dict(request.form.items())['phone']

		phone = int(str(code) + str(phone))

		User.create_user(username='unknown', email=email, password=password, address=address,
			account_type=account_type, phone=phone)

		user = User.get(User.email==email)

		login_user(user)

		if user.account_type == 'buyer':
			return redirect(url_for('buyer'))
		elif user.account_type == 'supplier':
			return redirect(url_for('supplier'))
		else:
			redirect(url_for('shipping'))

	except KeyError:
		flash('Please fill all fields')
		return render_template('supplier-register.html')

@app.route('/', methods=['POST', 'GET'])
def index():
	products = Product.select().limit(10)

	#return render_template('index.html', products=products)
	return redirect(url_for('buyer_feed'))

@app.route('/login', methods=['POST', 'GET'])
def login():
	login_form = forms.LoginForm()

	if login_form.validate_on_submit():
		try:
			user = User.get(User.email == login_form.email.data)

			login_user(user)

			if user.account_type == 'buyer':
				return redirect(url_for('buyer'))
			elif user.account_type == 'supplier':
				return redirect(url_for('seller_feed'))
			else:
				redirect(url_for('shipping'))
		except DoesNotExist:
			pass

	return render_template('login.html', form=login_form)

@app.route('/logout', methods=['POST', 'GET'])
def logout():
	logout_user()
	return redirect(url_for('login'))

@app.route('/buyer')
@login_required
def buyer():
	stocks = Stock.select().where(Stock.bought==False)
	my_orders = current_user.orders.order_by(Order.date_ordered.desc())

	return render_template('buyer-dashboard.html', stocks=stocks,
		Order=Order, Stock=Stock, fn=fn, my_orders=my_orders, list=list)

@app.route('/buyer/notifications')
@login_required
def buyer_notifications():
	my_orders = current_user.orders.where(Order.ready==True).order_by(Order.date_ordered.desc())

	return render_template('buyer-notifications.html',
		Order=Order, Stock=Stock, fn=fn, my_orders=my_orders, list=list)

@app.route('/buyer/cart')
@login_required
def buyer_orders():
	my_orders = current_user.orders.where(Order.ready==False).order_by(Order.date_ordered.desc())

	return render_template('buyer-orders.html',
		Order=Order, Stock=Stock, fn=fn, my_orders=my_orders, list=list)

@app.route('/buyer/feed/', defaults={'page': 1}, methods=['POST', 'GET'])
@app.route('/buyer/feed/<product>/<page>')
@app.route('/buyer/feed/page/<int:page>')
@login_required
def buyer_feed(page, product=None):

	if product == None:
		stocks = Stock.select().where(Stock.bought==False).paginate(int(page), PER_PAGE)
		count = Stock.select().where(Stock.bought==False).count()
	else:
		stocks = Product.get(Product.name==product).in_stock.where(Stock.bought==False).paginate(int(page), PER_PAGE)
		count = Product.get(Product.name==product).in_stock.where(Stock.bought==False).count()

	stocks = [{'id': json.dumps(str(stock.id)) , 'stock': stock, 'form': forms.OrderForm() } for stock in stocks] # this will be used for adding listings to the homepage

	stock_ids = [stock['id'] for stock in stocks ]

	pagination = Pagination(page, PER_PAGE, count)

	return render_template('buyer-feed.html', stocks=stocks, current_user=current_user,
		Order=Order, Stock=Stock, fn=fn, int=int, pagination=pagination, page=page, os=os,
		HOST=HOST, PORT=PORT, UPLOAD_FOLDER=UPLOAD_FOLDER)

@app.route('/seller/feed/', defaults={'page': 1}, methods=['POST', 'GET'])
@app.route('/seller/feed/<product>/<page>')
@app.route('/seller/feed/page/<int:page>')
@login_required
def seller_feed(page, product=None):

	if product == None:
		stocks = Stock.select().where(Stock.bought==False).paginate(int(page), 100)
		count = Stock.select().where(Stock.bought==False).count()
	else:
		stocks = Product.get(Product.name==product).in_stock.where(Stock.bought==False).paginate(int(page), 100)
		count = Product.get(Product.name==product).in_stock.where(Stock.bought==False).count()

	stocks = [{'id': json.dumps(str(stock.id)) , 'stock': stock, 'form': forms.OrderForm() } for stock in stocks] # this will be used for adding listings to the homepage

	stock_ids = [stock['id'] for stock in stocks ]

	pagination = Pagination(page, 100, count)

	return render_template('admin-feed.html', stocks=stocks, current_user=current_user,
		Order=Order, Stock=Stock, fn=fn, int=int, pagination=pagination, page=page, os=os,
		list=list, HOST=HOST)

@app.route('/buyer/how-it-works', methods=['POST', 'GET'])
@login_required
def buyer_how_it_works():
	stocks = Stock.select().where(Stock.bought==False)
	stocks = [{'id': json.dumps(str(stock.id)) , 'stock': stock } for stock in stocks] # this will be used for adding listings to the homepage
	units = Unit.select()

	return render_template('buyer-how-it-works.html', stocks=stocks, Order=Order,
			current_user=current_user, Stock=Stock, fn=fn, units=units)


@app.route('/buyer/make-suggestion', methods=['POST', 'GET'])
@login_required
def buyer_make_suggestion():
	stocks = Stock.select().where(Stock.bought==False)
	stocks = [{'id': json.dumps(str(stock.id)) , 'stock': stock } for stock in stocks] # this will be used for adding listings to the homepage
	units = Unit.select()

	try:
		suggestion = dict(request.form.items())['suggestion']
		#scale = int(dict(request.form.items())['scale']) removed for now

		Suggestion.make_suggestion(suggestion=suggestion, scale=0, user=current_user.id)
		flash('Suggestion submitted. Thank you!', 'success')
		return redirect(url_for('buyer_make_suggestion'))
	except KeyError: #some required fields blanks
		return render_template('buyer-make-suggestion.html', stocks=stocks,
			current_user=current_user, Order=Order, Stock=Stock, fn=fn, units=units
		)
	except ValueError: #scale was text not number
		flash('Invalid entry. Please try again', 'error')
		return redirect(url_for('buyer_make_suggestion'))

@app.route('/seller')
@login_required
def supplier():
	stocks = Stock.select().where(Stock.bought==False)
	stocks = [{'id': json.dumps(str(stock.id)) , 'stock': stock } for stock in stocks] # this will be used for adding listings to the homepage
	my_stocks = current_user.products

	tags = [product.name for product in Product.select()]
	tags += [descriptor.description for descriptor in Descriptor.select()]
	tags += [brand.name for brand in Brand.select()]
	tags.sort()

	return render_template('supplier_dashboard.html', stocks=stocks, current_user=current_user,
		Order=Order, Stock=Stock, tags=tags, fn=fn, my_stocks=my_stocks, list=list)

@app.route('/seller/add-product', methods=['POST', 'GET'])
@login_required
def seller_add_product():
	add_product_form = forms.AddProductForm()
	add_product_form.units.choices = getUnits()

	# there vars provide data for the datalists in the form
	stocks = Stock.select().where(Stock.bought==False)
	stocks = [{'id': json.dumps(str(stock.id)) , 'stock': stock } for stock in stocks] # this will be used for adding listings to the homepage
	units = Unit.select()
	brands = Brand.select()
	descriptions = Descriptor.select()
	products = Product.select()
	prices = Stock.select(Stock.price)

	if add_product_form.validate_on_submit():
		product = add_product_form.product.data
		brand = add_product_form.brand.data
		description = add_product_form.description.data
		quantity = add_product_form.quantity.data
		price = add_product_form.price.data
		unit = add_product_form.units.data
		target = add_product_form.target.data
		moq = add_product_form.moq.data

		product, created = Product.create_or_get(name=product)
		brand, created = Brand.create_or_get(name=brand)
		description, created = Descriptor.create_or_get(description=description)
		unit = Unit.get(Unit.id==unit)

		filename = '{}{} {} {} {} {}.png'.format(quantity, unit.short_name, brand.name,
			description.description, product.name, randint(0, 9999999999))
		#filename = secure_filename(add_product_form.image.data.filename)
		add_product_form.image.data.save(app.config['UPLOAD_FOLDER'] + filename)

		#create stock
		stock, created = Stock.get_or_create(product=product, brand=brand, first_description=description,
				quantity=quantity, price=price, unit=unit, supplier=current_user.id,
				minimum_quantity=target, moq=moq, image=filename)

		if created == False:
			flash('Stock item already exists', 'red')
		else:
			flash('Stock item successfully added.', 'green')

	return render_template('seller-add-product.html', stocks=stocks,
			current_user=current_user, brands=brands, Order=Order,
			Stock=Stock, fn=fn, descriptions=descriptions, units=units,
			products=products, prices=prices, form=add_product_form)

@app.route('/seller/make-suggestion', methods=['POST', 'GET'])
@login_required
def seller_make_suggestion():
	stocks = Stock.select().where(Stock.bought==False)
	stocks = [{'id': json.dumps(str(stock.id)) , 'stock': stock } for stock in stocks] # this will be used for adding listings to the homepage
	units = Unit.select()

	try:
		suggestion = dict(request.form.items())['suggestion']
		#scale = int(dict(request.form.items())['scale']) removed for now

		Suggestion.make_suggestion(suggestion=suggestion, scale=0, user=current_user.id)
		flash('Suggestion submitted. Thank you!', 'success')
		return redirect(url_for('seller_make_suggestion'))
	except KeyError: #some required fields blanks
		return render_template('seller-make-suggestion.html', stocks=stocks,
			current_user=current_user, Order=Order, Stock=Stock, fn=fn, units=units
		)
	except ValueError: #scale was text not number
		flash('Invalid entry. Please try again', 'error')
		return redirect(url_for('seller_make_suggestion'))

@app.route('/shipping')
def shipping():

	tags = [product.name for product in Product.select()]
	tags += [descriptor.description for descriptor in Descriptor.select()]
	tags += [brand.name for brand in Brand.select()]
	tags.sort()

	return render_template('shipper_dashboard.html', Order=Order, Stock=Stock,
		tags=tags, fn=fn, current_user=current_user)

@app.route('/supplier/submit-product')
@login_required
def submit_product():
	return render_template('supplier_submit_product.html', current_user=current_user)

@app.route('/order', methods=['POST'])
@login_required
def order():
	quantity = int(dict(request.form.items())['quantity'])
	stock_id = dict(request.form.items())['stock_id']
	page = dict(request.form.items())['page']
	stock = Stock.get(Stock.id==stock_id)

	# have to make sure that the person making an order is a buyer
	if current_user.account_type == 'buyer':
		response = process_order(quantity=quantity, stock=stock)
		flash(response['response'], response['category'])
	else:
		flash('You need a buyer account to participate in group buying.', 'red')

	return redirect('{}page/{}'.format(url_for('buyer_feed'), page))

def getUnits():
	units = Unit.select()

	optimised_units = [(unit.id, unit.short_name) for unit in units]

	return optimised_units

def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)
app.jinja_env.globals['url_for_other_page'] = url_for_other_page

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html', Order=Order), 404

@app.errorhandler(500)
def internal_server_errror(e):
    return render_template('500.html'), 500

@app.route('/about')
def about():
	return render_template('about-roundshopper.html')


socketio = SocketIO(app)

@app.route('/socket')
def the_start():
    return render_template('socket.html')

@socketio.on('my event', namespace='/test')
def test_message(message):
    emit('my response', {'data': message['data']})

@socketio.on('my broadcast event', namespace='/test')
def test_message(message):
    emit('my response', {'data': message['data']}, broadcast=True)

@socketio.on('connect', namespace='/test')
def test_connect():
    emit('my response', {'data': 'Connected'})

@socketio.on('disconnect', namespace='/test')
def test_disconnect():
    print('Client disconnected')

if __name__ == '__main__':
	socketio.run(app, debug=True, host=HOST, port=PORT)
	# main_thread = Thread(target=app.run)
	# main_thread.daemon = True
	# main_thread.start()

	# socket_thread = Thread(target=manage_socket_service)
	# socket_thread.daemon = True
	# socket_thread.start()

	# t.daemon = True  # thread dies when main thread (only non-daemon thread) exits.
	# t.start()
	# app.run(debug=DEBUG, port=PORT, host=HOST)
	# #app.run(debug=DEBUG, host=HOST, port=PORT)
	# # start and manage socket services
	# manage_socket_service()
