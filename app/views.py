from app import app, db, cache, console
from flask import render_template, redirect, url_for, request, send_from_directory, abort, jsonify
import os
from shutil import move
from werkzeug import secure_filename
from werkzeug.wrappers import Response
from random import random
from forms import PostSongForm, PostAlbumForm, SongDataForm, AlbumDataForm
from models import Artist, Album, Song, dud
from sockets import UpdateNamespace
import music
from pickle import dump, load
from gevent import monkey, sleep

@app.route('/')
def home():
    current, playlist = music.get_playlist()
    playlist = [Song.query.filter_by(id=pk).first() for pk in playlist]
    current = Song.query.filter_by(id=current).first()
    form = PostAlbumForm()
    return render_template('home.html', form=form, current=current,
                           playlist=playlist, played=music.get_time())

@app.route('/instructions/')
def instructions():
    return render_template('instructions.html')

@app.route('/music/<filename>')
def get_song(filename):
    return send_from_directory(app.config['MUSIC_DIR'], filename)

@app.route('/post_album/', methods=['GET','POST'])
def post_album():
    """Takes an album posted by the user, stores it in a temporary
    directory, and ask the user to confirm that the automatically
    pulled metadata is correct"""

    #validate the form
    form = PostAlbumForm()
    if not form.validate():
        print 'invalid!'
        abort(403)

    #Create a unique batch directory in the temp folder
    while not 'batch_name' in locals() or \
        os.path.exists(os.path.join(app.config['TEMP_DIR'], batch_name)):
        batch_name = str(int(random() * 10**16))
    os.makedirs(os.path.join(app.config['TEMP_DIR'], batch_name))

    #Actually save the songs in that directory
    paths, filenames = [], []
    for song in form.songs.data:
        filename = secure_filename(song.filename)
        path = os.path.join(app.config['TEMP_DIR'],
                                batch_name, filename)
        song.save(path)
        paths.append(path)
        filenames.append(song.filename)

    #Now that they're saved, get the metadata
    metadatas = music.get_metadata(paths, filenames)
    album, artist = music.guess_album_and_artist(metadatas)
    #Generate an appropriate form using the metadata as defaults
    confirm_form = AlbumDataForm(formdata=None,album=album,artist=artist)
    for metadata, filename, path in zip(metadatas, filenames, paths):
        with open(path.split('.')[0] + '.metadata', 'w') as mfile:
            dump(metadata, mfile)
            #add the new row, using dud as an object with the wirght attributes
            confirm_form.uploads.append_entry(dud(song=metadata.get('title',''),
                                          track = metadata.get('track',''),
                                          filename = filename))
            
    return render_template('song_uploader.html', batch_name=batch_name, form=confirm_form, upload='album')


@app.route('/confirm_album/<batch_name>', methods=['GET','POST'])
def confirm_album(batch_name):
    """The last step in uploading a song, it takes a form filled with song
    metadata and puts the music in the database"""

    #Package data into a form
    form = AlbumDataForm(request.form)
    if not form.validate():
        print 'invalid!'
        abort(403)
    #Process the album data
    artist = Artist.query.filter_by(name=form.artist.data.title()).first()
    if not artist:
        artist = Artist(name=form.artist.data.title())
        db.session.add(artist)
    
    album = Album.query.filter(Album.title==form.album.data.title(),
                               Album.artist==artist).first()
    if not album:
        album = Album(title=form.album.data.title(), artist=artist)
        db.session.add(album)
    #Process the data for each song and save the songs
    for upload in form.uploads.data:
        source = os.path.join(app.config['TEMP_DIR'],
                              batch_name, secure_filename(upload['filename']))  
        msource = source.split('.')[0] + '.metadata'
        song = Song.query.filter(Song.title==upload['song'],
                                 Song.album==album,
                                 Song.artist==artist).first()
        if song: 
            os.remove(source)
            os.remove(msource)
        else:
            with open(msource) as mfile:
                metadata = load(mfile)
            song = Song(title=upload['song'], artist=artist, album=album, length=metadata['length'], extension=metadata['extension'], track=upload['track'])
            destination = music.get_path_from_song(song)
            db.session.add(song)
            outer_dir = '/'.join(destination.split('/')[:-1])
            if not os.path.exists(outer_dir):
                os.makedirs(outer_dir)
            move(source, destination)
            os.remove(msource)
            db.session.commit()

    os.rmdir(os.path.join(app.config['TEMP_DIR'],batch_name))

    form = PostAlbumForm(formdata=None)
    return render_template('song_uploader.html', form=form, uploaded=True, upload='None')


@app.route('/play/')
def play():
    music.play()
    return Response(status=204)

@app.route('/pause/')
def pause():
    music.pause()
    return Response(status=204)

#a person-friendly shortcut
@app.route('/next/')
def next():
    music.next_song()
    return Response(status=204)

