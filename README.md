# Write to your MP

Campaign groups sometimes encourage their supporters to email their MP with a pre-written letter prepared by
the campaigners. Whilst this makes it easy for people to communicate their support for the issue in question,
a form letter is less persuasive than a real letter.

With this tool, you can allow people to write to their MP about a particular issue, and give them appropriate
guidance about what to write. This advice can be different for different MPs: you can divide the MPs into groups
that you define, and present different advice depending on the group. For example, the appropriate advice may
be different depending on the MPs past voting record on your particular issue.

The user is directed to the MySociety [WriteToThem](http://www.writetothem.com/) site to send the message,
once they have composed it.

## How to install this application

This code is distributed as an application that runs on [Google App Engine](http://code.google.com/appengine/).
It can be incorporated into an existing App Engine site, or run separately. For example, if your main web site
is at www.example.org you could run this application on a subdomain such as mp.example.org.

The rest of these instructions assume you want to install it as a separate application.

### Basic setup

1. You need a Google account. If you have a GMail address, that will do. If not, you can make a Google account
   by filling in [this form](https://www.google.com/accounts/NewAccount).
2. Download this application from <http://github.com/robinhouston/write-to-mp/downloads> and unzip it – or check out the git repository, if you know how to do that.
3. Register for a [TheyWorkForYou API key](http://www.theyworkforyou.com/api/key).
4. Edit the file `handlers.py` and insert your API key where indicated, on line 25 of the file.

### See if it works on your computer

1. Download the [Google App Engine SDK for Python](http://code.google.com/appengine/downloads.html#Google_App_Engine_SDK_for_Python) and install it on your computer.
2. Run the Google App Engine Launcher.
3. Choose "Add existing application", and select the directory containing this application.
4. Click the Run button.
5. Go to http://localhost:8080/mp/write in your web browser, and make sure a page appears.

**For advanced users**: There is a test data set distributed with this code, in the file
`data/test-data.sqlite`. You can tell the dev appserver to use this data file by passing
the command-line options `--use_sqlite --datastore_path=data/test-data.sqlite`. This contains
the list of MPs as of 30 August 2010.

### Get the real thing working

1. Create a Google App Engine application [here](https://appengine.google.com/).
2. Edit the file `app.yaml` and insert the name of your application on the first line, in place of
   `write-to-mp`.
3. Click the Publish button in the Google App Engine Launcher.
4. Check you can see the page you looked at on your computer by going to
   http://your-app-id.appspot.com/mp/write, replacing `your-app-id` with the id of your application,
   which you chose in step 1.
5. Tell the application to download the list of MPs from TheyWorkForYou by going to
   http://your-app-id.appspot.com/mp/cron/new_mps
   You will have to log in using your Google account at this point. If this step works
   correctly, you will see the message "Fetching new MPs in the background".
6. You can monitor the progress of the download by loading http://your-app-id.appspot.com/mp/admin/list
   and reloading it periodically to check that the list is updating.

### Associate it with the domain name you want to use

1. [Register your domain for Google Apps](https://www.google.com/a/cpanel/domain/new),
   if you haven't already.
2. Follow [these instructions](http://code.google.com/appengine/articles/domains.html).

## How to use it

### Setting up the advice

At its most basic, you can just go to http://your-app-id.appspot.com/mp/admin and put in some
advice. If you want your advice to be shown as collapsible sections that can be expanded by
clicking, you have to format it in a specific way, like this:
    1. First collapsible section
    
        * bullet point, which can have a whole paragraph of text.
        * another bullet point
    
    2. Second collapsible section
    
        * bullet point here
        * etc.
Note that the placement of blank lines and the precise number of spaces before
a star is crucial. You may have to use some trial-and-error to get it right!

You should also edit the file `mp/enter.html` and change the introductory text to explain
your campaign. Delete everything between the markers

    <!-- v v Replace everything from this comment to the following one. v v -->
and
    <!-- ^ ^ Replace everything up to this comment from the previous one. ^ ^ -->
and replace it with the text you want, in HTML format. (You can just wrap each paragraph
in a pair &lt;p&gt; &hellip; &lt;/p&gt;.)

### Grouping MPs

You can also create groups of MPs, by clicking the "New group" button and entering
appropriate text. You can add MPs to the group by typing their names, or by using
the list interface and choosing the appropriate group from the dropdown menu.

### Finally

Before running a campaign you should check that <team@writetothem.com> are happy with it,
since it relies on their service for sending the messages.

## Customising the appearance

The appearance of the pages can be customised by editing the master template `mp/template.html`
and the style sheet `styles/common.css`.

### History

Developed for the [10:10 Lighter Later](http://www.lighterlater.org/) campaign.

### Author

Written by Robin Houston <robin+ghmp@1010uk.org>.

### Copyright
This code is copyright [10:10](http://www.1010uk.org/), 2010, and is made available under the terms of the GNU GPL v2.
