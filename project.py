import httplib2
import json
import random
import requests
import string

from flask import Flask, render_template, request, make_response
from flask import redirect, jsonify, url_for, flash
from flask import session as login_session

from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError

from database_setup import Base, Restaurant, MenuItem, User

app = Flask(__name__)

# Database connection
engine = create_engine('sqlite:///restaurantmenuwithusers.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Find user and return user id or None if not found
def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


# Find and return user object
def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


# Create new user object and put in database
def createUser(login_session):
    newUser = User(
        name=login_session['username'],
        email=login_session['email'],
        picture=login_session['picture']
    )
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()

    return user.id


# Login and generate state
@app.route('/login')
def showLogin():
    state = ''.join(
        random.choice(
            string.ascii_uppercase + string.digits
        ) for x in xrange(32)
    )
    login_session['state'] = state

    return render_template('login.html', STATE=state)


# Login using facebook oauth2
@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    # If states don't match, return invalid response
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    access_token = request.data

    # Load facebook secrets and retrieve access token
    f = json.loads(open('fb_client_secrets.json', 'r').read())
    app_id = f['web']['app_id']
    app_secret = f['web']['app_secret']
    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_'
    url += 'exchange_token&client_id='
    url += '%s&client_secret=%s&fb_exchange_token=%s' % (
        app_id,
        app_secret,
        access_token
    )
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    token = json.loads(result)['access_token']

    url = 'https://graph.facebook.com/v2.8/me?access_'
    url += 'token=%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    data = json.loads(result)

    # Save user and access token data to current login session
    login_session['username'] = data['name']
    login_session['email'] = data['email']
    login_session['facebook_id'] = data['id']
    login_session['access_token'] = token

    url = 'https://graph.facebook.com/v2.8/me/picture?access_'
    url += 'token=%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    login_session['picture'] = data['data']['url']

    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    # Make the picture look nice
    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']

    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += '"style="width: 300px; height: 300px; border-radius: 150px; '
    output += '-webkit-border-radius: 150px; -moz-border-radius: 150px;">'

    flash('You are now logged in as %s' % login_session['username'])
    return output


# Log out of the application
@app.route('/disconnect')
def disconnect():
    # Check for if user tries to disconnect without having logged in
    if 'username' not in login_session:
        return redirect('/login')

    facebook_id = login_session['facebook_id']
    access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (
        facebook_id,
        access_token
    )
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]

    # Delete all data from current login session
    del login_session['username']
    del login_session['email']
    del login_session['facebook_id']
    del login_session['access_token']
    del login_session['picture']
    del login_session['user_id']

    flash('You have successfully been logged out.')
    return redirect(url_for('showRestaurants'))


# JSON endpoint for a restaurant's menu
@app.route('/restaurant/<int:restaurant_id>/menu/JSON')
def restaurantMenuJSON(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(
        id=restaurant_id
    ).one()

    items = session.query(MenuItem).filter_by(
        restaurant_id=restaurant_id
    ).all()

    return jsonify(MenuItems=[i.serialize for i in items])


# JSON endpoint for an item in a restaurant's menu
@app.route('/restaurant/<int:restaurant_id>/menu/<int:menu_id>/JSON')
def menuItemJSON(restaurant_id, menu_id):
    Menu_Item = session.query(MenuItem).filter_by(
        id=menu_id
    ).one()

    return jsonify(Menu_Item=Menu_Item.serialize)


# JSON endpoint for all restaurants
@app.route('/restaurant/JSON')
def restaurantsJSON():
    restaurants = session.query(Restaurant).all()

    return jsonify(restaurants=[r.serialize for r in restaurants])


# Show the main page and all restaurants
@app.route('/')
@app.route('/restaurant/')
def showRestaurants():
    restaurants = session.query(Restaurant).order_by(asc(Restaurant.name))
    return render_template('restaurants.html', restaurants=restaurants)


# Create a new restaurant
@app.route('/restaurant/new/', methods=['GET', 'POST'])
def newRestaurant():
    # Make sure user is logged in
    if 'username' not in login_session:
        return redirect('/login')

    if request.method == 'POST':
        newRestaurant = Restaurant(
            name=request.form['name'],
            user_id=login_session['user_id']
        )
        session.add(newRestaurant)
        session.commit()

        flash('New Restaurant %s Successfully Created' % newRestaurant.name)
        return redirect(url_for('showRestaurants'))
    else:
        return render_template('newRestaurant.html')


# Edit a restaurant
@app.route('/restaurant/<int:restaurant_id>/edit/', methods=['GET', 'POST'])
def editRestaurant(restaurant_id):
    # Make sure user is logged in
    if 'username' not in login_session:
        return redirect('/login')

    editedRestaurant = session.query(Restaurant).filter_by(
        id=restaurant_id
    ).one()

    user_id = getUserID(login_session['email'])
    if editedRestaurant.user_id != user_id:
        flash('You are not the owner of the restaurant.')
        return redirect(url_for('showRestaurants'))

    if request.method == 'POST':
        if request.form['name']:
            editedRestaurant.name = request.form['name']

            flash('Restaurant Successfully Edited %s' % editedRestaurant.name)
            return redirect(url_for('showRestaurants'))
    else:
        return render_template(
            'editRestaurant.html',
            restaurant=editedRestaurant
        )


# Delete a restaurant
@app.route('/restaurant/<int:restaurant_id>/delete/', methods=['GET', 'POST'])
def deleteRestaurant(restaurant_id):
    # Make sure user is logged in
    if 'username' not in login_session:
        return redirect('/login')

    restaurantToDelete = session.query(Restaurant).filter_by(
        id=restaurant_id
    ).one()

    user_id = getUserID(login_session['email'])
    if restaurantToDelete.user_id != user_id:
        flash('You are not the owner of the restaurant.')
        return redirect(url_for('showRestaurants'))

    if request.method == 'POST':
        session.delete(restaurantToDelete)
        session.commit()

        flash('%s Successfully Deleted' % restaurantToDelete.name)
        return redirect(url_for(
            'showRestaurants',
            restaurant_id=restaurant_id
        ))
    else:
        return render_template(
            'deleteRestaurant.html',
            restaurant=restaurantToDelete
        )


# Display a restaurant's menu
@app.route('/restaurant/<int:restaurant_id>/')
@app.route('/restaurant/<int:restaurant_id>/menu/')
def showMenu(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    items = session.query(MenuItem).filter_by(
        restaurant_id=restaurant_id
    ).all()

    return render_template('menu.html', items=items, restaurant=restaurant)


# Create a new menu item
@app.route(
    '/restaurant/<int:restaurant_id>/menu/new/',
    methods=['GET', 'POST']
)
def newMenuItem(restaurant_id):
    # Make sure user is logged in
    if 'username' not in login_session:
        return redirect('/login')

    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()

    user_id = getUserID(login_session['email'])
    if restaurant.user_id != user_id:
        flash('You are not the owner of the restaurant.')
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))

    if request.method == 'POST':
        newItem = MenuItem(
            name=request.form['name'],
            description=request.form['description'],
            price=request.form['price'],
            course=request.form['course'],
            restaurant_id=restaurant_id,
            user_id=restaurant.user_id
        )
        session.add(newItem)
        session.commit()

        flash('New menu %s item successfully created' % (newItem.name))
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))
    else:
        return render_template('newMenuItem.html', restaurant_id=restaurant_id)


# Edit a menu item
@app.route(
    '/restaurant/<int:restaurant_id>/menu/<int:menu_id>/edit',
    methods=['GET', 'POST']
)
def editMenuItem(restaurant_id, menu_id):
    # Make sure user is logged in
    if 'username' not in login_session:
        return redirect('/login')

    editedItem = session.query(MenuItem).filter_by(id=menu_id).one()
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()

    user_id = getUserID(login_session['email'])
    if restaurant.user_id != user_id:
        flash('You are not the owner of the restaurant.')
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))

    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        if request.form['price']:
            editedItem.price = request.form['price']
        if request.form['course']:
            editedItem.course = request.form['course']

        session.add(editedItem)
        session.commit()

        flash('Menu Item Successfully Edited')
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))
    else:
        return render_template(
            'editMenuItem.html',
            restaurant_id=restaurant_id,
            menu_id=menu_id,
            item=editedItem
        )


# Delete a menu item
@app.route(
    '/restaurant/<int:restaurant_id>/menu/<int:menu_id>/delete',
    methods=['GET', 'POST']
)
def deleteMenuItem(restaurant_id, menu_id):
    # Make sure user is logged in
    if 'username' not in login_session:
        return redirect('/login')

    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    itemToDelete = session.query(MenuItem).filter_by(id=menu_id).one()

    user_id = getUserID(login_session['email'])
    if restaurant.user_id != user_id:
        flash('You are not the owner of the restaurant.')
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))

    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()

        flash('Menu Item Successfully Deleted')
        return redirect(url_for('showMenu', restaurant_id=restaurant_id))
    else:
        return render_template(
            'deleteMenuItem.html',
            restaurant_id=restaurant_id,
            item=itemToDelete
        )


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
