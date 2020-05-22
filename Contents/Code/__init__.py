############################################################################
# This plugin will create a list of medias in a section of Plex as a csv file,
# or as an xlsx file
#
# Made by
# dane22....A Plex Community member
# srazer....A Plex Community member
# CCarpo....A Plex Community member
#
#############################################################################

# To find Work in progress, search this file for the
#  word ToDo in all the modules
# TODO: Poster view for first menu

import os
import sys
import time
import io
import csv
import re
import locale
import json
import plistlib
import movies
import tvseries
import audio
import photo
import misc
import playlists
import moviefields
import audiofields
import tvfields
import photofields
from consts import NAME, VERSION, PREFIX, ICON, ART, PLAYLIST, APPNAME
from consts import CONTAINERSIZEMOVIES, PMSTIMEOUT, CONTAINERSIZETV
from consts import CONTAINERSIZEEPISODES, CONTAINERSIZEPHOTO
from consts import CONTAINERSIZEAUDIO, PLAYCOUNTEXCLUDE, IOENCODING


import output

# Threading stuff
# Current status of the background scan
bScanStatus = 0
# When starting a scan, how long in seconds to wait before
# displaying a status page. Needs to be at least 1.
initialTimeOut = 12
# Type of section been exported
sectiontype = ''
# Number of item currently been investigated
bScanStatusCount = 0
# Path to export file
EXPORTPATH = ''


@route(PREFIX + '/launch')
def launch(title='', skipts='False', level=None, playlist='False'):
    '''
    Used to launch an export from an url
    Syntax is:
    http://IP-OF-PMS:32400/applications/ExportTools/launch?title=TITLE-OF-SECTION&skipts=False&level=Level%203&playlist=False&X-Plex-Token=MY-TOKEN
    '''
    skipts = (skipts.upper() == 'TRUE')
    playlist = (playlist.upper() == 'TRUE')
    outFile = output.getOutFileName(
        title=title,
        skipts=skipts,
        level=level,
        playlist=playlist)

    strFeedback = ''.join((
        'I was asked via url to scan section: "%s" ' % (title),
        'with skip timestamp set to "%s" ' % (str(skipts)),
        'and with a level of "%s". ' % (level),
        'PlayList is set to %s. ' % (playlist),
        'Output file is: "%s"' % (outFile)
    ))
    Log.Debug(strFeedback)
    ValidateExportPath()
    try:
        if playlist:
            scanPListFromPrefsOrURL(title=title, skipts=skipts, level=level)
        else:
            ScanLib(title=title, skipts=skipts, level=level)
        return strFeedback
    except Exception, e:
        if str(e) == 'list index out of range':
            return 'Library not found'
        else:
            return str(e)


@route(PREFIX + '/scanPListFromPrefsOrURL')
def scanPListFromPrefsOrURL(title='', skipts=False, level=None):
    Log.Debug('Starting to scan Playlist from prefs: %s' % title)
    # Get list of Playlists
    PlayListsURL = misc.GetLoopBack() + '/playlists'
    PlayLists = XML.ElementFromURL(PlayListsURL).xpath(
        '//Playlist[@title="' + title + '"]')
    key = PlayLists[0].get('key').decode('utf-8')
    PlayListType = PlayLists[0].get('playlistType').decode('utf-8')
    Log.Debug('Key detected as %s and type as %s' % (key, PlayListType))
    Thread.Create(
        backgroundScanThread,
        globalize=True,
        title=title,
        key=key,
        sectiontype='playlists',
        skipts=skipts,
        level=level
        )
    return


@route(PREFIX + '/restart')
def restart():
    try:
        Log.Debug('Restarting plugin')
        pFile = Core.storage.join_path(
            Core.app_support_path,
            Core.config.bundles_dir_name,
            APPNAME + '.bundle',
            'Contents',
            'Info.plist')
        pl = plistlib.readPlist(pFile)
        url = ''.join((
            misc.GetLoopBack(),
            '/:/plugins/%s/restart')) % pl[
                'CFBundleIdentifier']
        HTTP.Request(misc.GetLoopBack() + '/:/plugins/%s/restart' % pl[
            'CFBundleIdentifier'],
            cacheTime=0,
            immediate=True)
    except Exception, e:
        try:
            HTTP.Request(
                misc.GetLoopBack() + '/:/plugins/com.plexapp.system/restart',
                immediate=True)
        except Exception, e:
            pass


@route(PREFIX + '/sectionList')
def sectionList():
    # Path to DefaultPrefs.json
    prefsFile = Core.storage.join_path(
        Core.app_support_path,
        Core.config.bundles_dir_name,
        APPNAME + '.bundle', 'Contents', 'DefaultPrefs.json')
    try:
        with io.open(prefsFile) as json_file:
            data = json.load(json_file)
    except Exception, e:
        with io.open(prefsFile, encoding='utf8') as json_file:
            data = json.load(json_file)
    # Get list of libraries
    SectionsURL = misc.GetLoopBack() + '/library/sections'
    SectionList = XML.ElementFromURL(SectionsURL).xpath('//Directory')
    LibraryValues = []
    LibraryValues.append('*** Idle ***'.decode('utf-8'))
    LibraryValues.append('*** Reload Library List ***'.decode('utf-8'))
    for Section in SectionList:
        LibraryValues.append(Section.get('title').decode('utf-8'))
    for item in data:
        if item['id'] == 'Libraries':
            item['values'] = LibraryValues
            break
    PlayListValues = []
    PlayListValues.append('*** Idle ***'.decode('utf-8'))
    PlayListValues.append('*** Reload Playlists ***'.decode('utf-8'))
    PlayListURL = misc.GetLoopBack() + '/playlists'
    PlayLists = XML.ElementFromURL(PlayListURL).xpath('//Playlist')
    for PlayList in PlayLists:
        PlayListValues.append(PlayList.get('title').decode('utf-8'))
    for item in data:
        if item['id'] == 'Playlists':
            item['values'] = PlayListValues
            break
    try:
        with io.open(prefsFile, 'wb') as outfile:
            json.dump(data, outfile, indent=4)
    except Exception, e:
        try:
            Log.Debug('Exception handling due to', str(e))
            with io.open(prefsFile, 'wb', encoding='utf8') as outfile:
                json.dump(data, outfile, indent=4)
        except Exception, e:
            Log.Debug('Exception handling due to', str(e))
            with io.open(prefsFile, 'w', encoding='utf8') as outfile:
                json.dump(data, outfile, indent=4)
    restart()
    return


@route(PREFIX + '/genParam')
def genParam(url):
    ''' Generate params to WebCalls, based on url '''
    if EXTENDEDPARAMS != '':
        if '?' in url:
            url += EXTENDEDPARAMS
        else:
            url += '?' + EXTENDEDPARAMS[1:]
    return url


@route(PREFIX + '/genExtParam')
def genExtParam(sectionType='', level=None):
    '''
    Generate extended params to WebCalls, based on section type and level
    '''
    global EXTENDEDPARAMS
    EXTENDEDPARAMS = ''
    # Movies
    if sectionType == 'movie':
        if not level:
            level = Prefs['Movie_Level']
        if Prefs['Check_Files']:
            if level in [
                    "Level 3",
                    "Level 4",
                    "Level 5",
                    "Level 6",
                    "Special Level 1",
                    "Special Level 2",
                    "Level 666"
                    ]:
                EXTENDEDPARAMS += '&checkFiles=1'
        if level in [
                "Level 5",
                "Level 6",
                "Special Level 1",
                "Special Level 2",
                "Level 666"
                ]:
            EXTENDEDPARAMS += '&includeBandwidths=1'
        if level in [
                "Level 3",
                "Level 4",
                "Level 5",
                "Level 6",
                "Special Level 1",
                "Special Level 2",
                "Level 666"
                ]:
            EXTENDEDPARAMS += '&includeExtras=1'
        if level in [
                "Level 3",
                "Level 4",
                "Level 5",
                "Level 6",
                "Special Level 1",
                "Special Level 2",
                "Level 666"
                ]:
            EXTENDEDPARAMS += '&includeChapters=1'
    # Audio
    elif sectionType == "artist":
        if Prefs['Check_Files']:
            if Prefs['Artist_Level'] in ["Level 5", "Level 6", "Level 666"]:
                EXTENDEDPARAMS += '&checkFiles=1'
    # Shows
    elif sectionType == "show":
        if Prefs['Check_Files']:
            if level in [
                    "Level 4",
                    "Level 5",
                    "Level 6",
                    "Level 666"]:
                EXTENDEDPARAMS += '&checkFiles=1'
        if level in ["Level 4", "Level 5", "Level 6", "Level 666"]:
            EXTENDEDPARAMS += '&includeExtras=1'
        if level in ["Level 4", "Level 5", "Level 6", "Level 666"]:
            EXTENDEDPARAMS += '&includeBandwidths=1'
    # Playlists
    elif sectionType == "playlists":
        pass
    # Photos
    elif sectionType == "photo":
        if Prefs['Check_Files']:
            if Prefs['Photo_Level'] in [
                    "Level 4",
                    "Level 5",
                    "Level 6",
                    "Level 666"]:
                EXTENDEDPARAMS += '&checkFiles=1'
    return


def Start():
    ''' Start function '''
    global DEBUGMODE
    # Switch to debug mode if needed
    debugFile = Core.storage.join_path(
        Core.app_support_path,
        Core.config.bundles_dir_name,
        APPNAME + '.bundle',
        'debug')
    DEBUGMODE = os.path.isfile(debugFile)
    strLog = ''.join((
        '"*******  Started % s' % (NAME),
        ' on %s' % Platform.OS,
        ' at % s' % time.strftime("%Y-%m-%d %H:%M"),
        ' with locale set to % s' % str(locale.getdefaultlocale()),
        ' and file system encoding is % s' % str(sys.getfilesystemencoding()),
        ' **********'
    ))
    IOENCODING = str(sys.getfilesystemencoding())

    if DEBUGMODE:
        try:
            print strLog
        except Exception, e:
            pass
    Log.Debug(strLog)
    try:
        Log.Debug('Platform is %s' % (
            os.environ['PLEX_MEDIA_SERVER_INFO_VENDOR']))
    except Exception, e:
        pass
    try:
        Log.Debug('Device is %s' % (
            os.environ['PLEX_MEDIA_SERVER_INFO_DEVICE']))
    except Exception, e:
        pass
    try:
        Log.Debug('Model is %s' % (
            os.environ['PLEX_MEDIA_SERVER_INFO_MODEL']))
    except Exception, e:
        pass
    try:
        Log.Debug('OS Version is %s' % (
            os.environ['PLEX_MEDIA_SERVER_INFO_PLATFORM_VERSION']))
    except Exception, e:
        pass
    Plugin.AddPrefixHandler(PREFIX, launch, NAME, ICON, ART)
    Plugin.AddViewGroup('List', viewMode='List', mediaType='items')
    Plugin.AddViewGroup("Details", viewMode="InfoList", mediaType="items")
    ObjectContainer.art = R(ART)
    ObjectContainer.title1 = NAME
    DirectoryObject.thumb = R(ICON)
    HTTP.CacheTime = 0
    Log.Debug('Misc module is version: %s' % misc.getVersion())


@handler(PREFIX, NAME, thumb=ICON, art=ART)
@route(PREFIX + '/MainMenu')
def MainMenu(random=0):
    ''' Main Menu '''
    Log.Debug("**********  Starting MainMenu  **********")
    global sectiontype
    title = NAME
    oc = ObjectContainer(
        title1=title,
        no_cache=True,
        no_history=True,
        art=R(ART))
    oc.view_group = 'List'
    try:
        if ValidateExportPath():
            title = 'playlists'
            key = '-1'
            thumb = R(PLAYLIST)
            sectiontype = title
            oc.add(DirectoryObject(
                key=Callback(selectPList),
                thumb=thumb,
                title='Export from "' + title + '"',
                summary='Export list from "' + title + '"'))
            strLog = ''.join((
                'Getting section List from: ',
                misc.GetLoopBack(),
                '/library/sections'
            ))
            Log.Debug(strLog)
            sections = XML.ElementFromURL(
                misc.GetLoopBack() + '/library/sections',
                timeout=float(PMSTIMEOUT)).xpath('//Directory')
            for section in sections:
                sectiontype = section.get('type')
                # ToDo: Remove artist when code is in place for it.
                if sectiontype != "photook":
                    title = section.get('title')
                    key = section.get('key')
                    thumb = misc.GetLoopBack() + section.get('thumb')
                    Log.Debug(
                        'Title of section is %s with a key of %s' % (
                            title, key))
                    oc.add(DirectoryObject(
                        key=Callback(
                            backgroundScan,
                            title=title,
                            sectiontype=sectiontype,
                            key=key,
                            random=time.clock()),
                        thumb=thumb,
                        title='Export from "' + title + '"',
                        summary='Export list from "' + title + '"'))
        else:
            oc.add(DirectoryObject(
                key=Callback(MainMenu, random=time.clock()),
                title="Select Preferences to set the export path"))
    except Exception, e:
        Log.Critical("Exception happened in MainMenu")
        raise
    oc.add(PrefsObject(title='Preferences', thumb=R(ICON)))
    Log.Debug("**********  Ending MainMenu  **********")
    return oc


@route(PREFIX + '/ValidateExportPath')
def ValidateExportPath():
    ''' Validate Export Path '''
    Log.Debug('Entering ValidateExportPath')
    if Prefs['Auto_Path']:
        return True
    # Let's check that the provided path is actually valid
    myPath = Prefs['Export_Path']
    Log.Debug('My master set the Export path to: %s' % myPath)
    try:
        # Let's see if we can add out subdirectory below this
        if os.path.exists(myPath):
            Log.Debug(
                'Master entered a path that already existed as: %s' % myPath)
            if not os.path.exists(os.path.join(myPath, APPNAME)):
                os.makedirs(os.path.join(myPath, APPNAME))
                Log.Debug(
                    'Created directory named: %s' % os.path.join(
                        myPath, APPNAME))
                return True
            else:
                Log.Debug('Path verified as already present')
                return True
        else:
            raise Exception("Wrong path specified as export path")
            return False
    except Exception, e:
        Log.Exception('Bad Export Path eith error: %s' % (str(e)))
        return False


@route(PREFIX + '/ResetToIdle')
def ResetToIdle():
    '''
    Reset Library and PlayList Prefs to idle
    '''
    pFile = Core.storage.join_path(
        Core.app_support_path,
        Core.config.bundles_dir_name,
        APPNAME + '.bundle',
        'Contents',
        'Info.plist')
    pl = plistlib.readPlist(pFile)
    CFBundleIdentifier = pl['CFBundleIdentifier']
    url = ''.join((
        misc.GetLoopBack(),
        '/:/plugins/',
        CFBundleIdentifier,
        '/prefs/set?Libraries=&Playlists='))
    HTTP.Request(url, cacheTime=0, immediate=True)
    return


@route(PREFIX + '/ScanLib')
def ScanLib(title='', skipts=False, level=None):
    Log.Debug('Starting to scan section from prefs: %s' % title)
    # Get list of libraries
    SectionsURL = misc.GetLoopBack() + '/library/sections'
    Library = XML.ElementFromURL(SectionsURL).xpath(
        '//Directory[@title="' + title + '"]')
    key = Library[0].get('key').decode('utf-8')
    sectiontype = Library[0].get('type').decode('utf-8')
    Log.Debug('Key detected as %s and type as %s' % (key, sectiontype))
    Thread.Create(
        backgroundScanThread,
        globalize=True,
        title=title,
        key=key,
        sectiontype=sectiontype,
        skipts=skipts,
        level=level
        )
    return


@route(PREFIX + '/ValidatePrefs')
def ValidatePrefs():
    '''
    Called by the framework every time a user changes the prefs
    '''
    # Handle Playlists
    SelectedPList = Prefs['Playlists']
    if SelectedPList == '*** Reload Playlists ***':
        # Start by flipping prefs back to idle
        ResetToIdle()
        ValidateExportPath()
        Thread.Create(sectionList(), globalize=True)
        return
    if SelectedPList not in ['*** Reload Playlists ***', '*** Idle ***', None]:
        ResetToIdle()
        ValidateExportPath()
        scanPListFromPrefsOrURL(title=SelectedPList)
        return
    SelectedLib = Prefs['Libraries']
    if SelectedLib == '*** Reload Library List ***':
        # Start by flipping prefs back to idle
        ResetToIdle()
        Thread.Create(sectionList(), globalize=True)
        return
    if SelectedLib not in [
        '*** Reload Library List ***',
            '*** Idle ***',
            None]:
        ScanLib(title=SelectedLib)
        ResetToIdle()
        return


@indirect
@route(PREFIX + '/complete')
def complete(title=''):
    ''' Export Complete. '''
    fileName = EXPORTPATH.split('.tmp-Wait-Please')[0]
    global bScanStatus
    Log.Debug("*******  All done, tell my Master  ***********")
    title = ('Export Completed for %s' % title)
    try:
        title = unicode(title, 'utf-8', 'replace')
    except TypeError:
        pass
    message = 'Check the file: %s' % EXPORTPATH
    try:
        message = unicode(message, 'utf-8', 'replace')
    except TypeError:
        pass
    oc2 = ObjectContainer(title1=title, no_history=True, message=message)
    oc2.add(
        DirectoryObject(
            key=Callback(
                MainMenu,
                random=time.clock()),
            title="Go to the Main Menu"))
    # Reset the scanner status
    bScanStatus = 0
    Log.Debug("*******  Ending complete  ***********")
    return oc2


@route(PREFIX + '/cancelScan')
def cancelScan():
    ''' Cancel scanning '''
    global bScanStatus
    bScanStatus = 3
    Log.Info('************ User canceled scanning ************')
    message = 'Canceling scanning'
    title = message
    oc2 = ObjectContainer(title1=title, message=message, no_history=True)
    oc2.add(DirectoryObject(
        key=Callback(MainMenu),
        title="Canceled...Go to the Main Menu"))
    return oc2


@route(PREFIX + '/backgroundScan')
def backgroundScan(title='', key='', sectiontype='', random=0, statusCheck=0):
    '''
    Start the scanner in a background thread and provide status while running
    Current status of the Background Scanner:
    0=not running, 1=db, 2=complete, 3=Canceling
    Errors: 91=unknown section type, 99=Other Error, 401= Authentication error
    '''
    Log.Debug("******* Starting backgroundScan *********")
    global bScanStatus
    # Current status count (ex. "Show 2 of 31")
    global bScanStatusCount
    global bScanStatusCountOf
    try:
        if bScanStatus == 0 and not statusCheck:
            bScanStatusCount = 0
            bScanStatusCountOf = 0
            # Start scanner
            Thread.Create(
                backgroundScanThread,
                globalize=True,
                title=title,
                key=key,
                sectiontype=sectiontype)
            # Wait 10 seconds unless the scanner finishes
            x = 0
            while (x <= initialTimeOut):
                time.sleep(1)
                x += 1
                if bScanStatus == 2:
                    Log.Debug(
                        "******** Scan Done, stopping wait ********")
                    Log.Debug("*******  All done, tell my Master  ***********")
                    fileName = EXPORTPATH.split('.tmp-Wait-Please')[0]
                    title = ('Export Completed for %s as %s' % (
                        title, fileName))
                    try:
                        title = unicode(title, 'utf-8', 'replace')
                    except TypeError:
                        pass
                    message = 'Check the file: %s' % fileName
                    try:
                        message = unicode(message, 'utf-8', 'replace')
                    except TypeError:
                        pass
                    oc2 = ObjectContainer(
                        title1=title,
                        no_cache=True,
                        message=message,
                        no_history=True)
                    # Reset the scanner status
                    bScanStatus = 0
                    Log.Debug("*******  Ending complete  ***********")
                    return oc2
                    break
                if bScanStatus == 3:
                    Log.Info('Canceled job')
                    break
                if bScanStatus >= 90:
                    Log.Debug(
                        "******** Error in thread, stopping wait ********")
                    break
        # Sometimes a scanStatus check will happen when a scan is running.
        # Usually from something weird in the web client.
        # This prevents the scan from restarting
        elif bScanStatus == 0 and statusCheck:
            Log.Debug(
                "backgroundScan statusCheck is set and no scan is running")
            oc2 = ObjectContainer(
                title1="Scan is not running.",
                no_history=True)
            oc2.add(
                DirectoryObject(
                    key=Callback(
                        MainMenu,
                        random=time.clock()),
                    title="Go to the Main Menu"))
            return oc2
        # Summary to add to the status
        summary = ''.join((
            'The Plex Server will only wait a few seconds for us to ',
            'work, so we run it in the background. This requires you ',
            'to keep checking on the status until it is complete.'))
        if bScanStatus == 1:
            # Scanning Database
            summary = summary + ''.join((
                " The Database is being exported. Exporting ",
                str(bScanStatusCount),
                " of ",
                str(bScanStatusCountOf),
                ". Please wait a few seconds and check the status again."
            ))
            oc2 = ObjectContainer(
                title1=''.join((
                    "Exporting the Database ",
                    str(bScanStatusCount),
                    " of ",
                    str(bScanStatusCountOf),
                    ".")),
                no_history=True)
            oc2.add(DirectoryObject(
                key=Callback(
                    backgroundScan,
                    random=time.clock(),
                    statusCheck=1,
                    title=title),
                title="Exporting the database. To update Status, click here.",
                summary=summary))
            oc2.add(DirectoryObject(
                key=Callback(
                    backgroundScan,
                    random=time.clock(),
                    statusCheck=1,
                    title=title),
                title=''.join((
                    "Exporting ",
                    str(bScanStatusCount),
                    " of ",
                    str(bScanStatusCountOf))),
                summary=summary))
            oc2.add(DirectoryObject(
                key=Callback(cancelScan),
                title='Cancel scanning'))
        elif bScanStatus == 2:
            # Show complete screen.
            oc2 = complete(title=title)
            return oc2
        elif bScanStatus == 3:
            # Show complete screen.
            oc2 = complete(title='Canceled')
            return oc2
        elif bScanStatus == 91:
            # Unknown section type
            summary = "Unknown section type returned."
            oc2 = ObjectContainer(title1="Results", no_history=True)
            oc2.add(DirectoryObject(
                key=Callback(
                    MainMenu,
                    random=time.clock()),
                title="*** Unknown section type. ***",
                summary=summary))
            oc2.add(
                DirectoryObject(
                    key=Callback(
                        MainMenu,
                        random=time.clock()),
                    title="*** Please submit logs. ***",
                    summary=summary))
            bScanStatus = 0
        elif bScanStatus == 99:
            # Error condition set by scanner
            summary = "An internal error has occurred. Please check the logs"
            oc2 = ObjectContainer(
                title1="Internal Error Detected. Please check the logs",
                no_history=True,
                view_group='List')
            oc2.add(DirectoryObject(
                key=Callback(MainMenu, random=time.clock()),
                title="An internal error has occurred.",
                summary=summary))
            oc2.add(DirectoryObject(
                key=Callback(MainMenu, random=time.clock()),
                title="*** Please submit logs. ***",
                summary=summary))
            bScanStatus = 0
        elif bScanStatus == 401:
            oc2 = ObjectContainer(title1="ERROR", no_history=True)
            # Error condition set by scanner
            summary = ''.join((
                "When running in like Home mode, ",
                "you must enable authentication in the preferences"))
            oc2 = ObjectContainer(title1=summary, no_history=True)
            oc2.add(DirectoryObject(
                key=Callback(MainMenu, random=time.clock()),
                title="Authentication error.",
                summary=summary))
            bScanStatus = 0
        else:
            # Unknown status. Should not happen.
            summary = ''.join((
                "Something went horribly wrong.",
                " The scanner returned an unknown status."))
            oc2 = ObjectContainer(title1="Uh Oh!.", no_history=True)
            oc2.add(
                DirectoryObject(
                    key=Callback(MainMenu, random=time.clock()),
                    title="*** Unknown status from scanner ***",
                    summary=summary))
            bScanStatus = 0
    except Exception, e:
        Log.Critical("Detected an exception in backgroundScan")
        raise
    Log.Debug("******* Ending backgroundScan ***********")
    return oc2


@route(PREFIX + '/backgroundScanThread')
def backgroundScanThread(title, key, sectiontype, skipts=False, level=None):
    ''' Background scanner thread. '''
    Log.Debug("*******  Starting backgroundScanThread  ***********")
    logSettings()
    global bScanStatus
    global bScanStatusCount
    global bScanStatusCountOf
    global EXPORTPATH
    try:
        bScanStatus = 1
        Log.Debug("Section type is %s" % sectiontype)
        # Generate parameters
        genExtParam(sectiontype, level)
        # Get level
        if level:
            myLevel = level
        elif sectiontype == 'show':
            myLevel = Prefs['TV_Level']
        elif sectiontype == 'movie':
            myLevel = Prefs['Movie_Level']
        elif sectiontype == 'artist':
            myLevel = Prefs['Artist_Level']
        elif sectiontype == 'photo':
            myLevel = Prefs['Photo_Level']
        elif sectiontype == 'playlists':
            myLevel = Prefs['PlayList_Level']
        else:
            myLevel = ''
        # Create the output file
        [outFile, myMediaURL] = output.createFile(
            key, sectiontype,
            title, skipts=skipts, level=myLevel)
        EXPORTPATH = outFile
        Log.Debug('Output file is named %s' % outFile)
        # Scan the database based on the type of section
        if sectiontype == "movie":
            scanMovieDB(myMediaURL, outFile, level=myLevel)
        elif sectiontype == "artist":
            scanArtistDB(myMediaURL, outFile, level=myLevel)
        elif sectiontype == "show":
            scanShowDB(myMediaURL, outFile, level=myLevel, key=key)
        elif sectiontype == "playlists":
            scanPList(myMediaURL, outFile, level=myLevel)
        elif sectiontype == "photo":
            scanPhotoDB(myMediaURL, outFile, level=myLevel)
        else:
            Log.Debug("Error: unknown section type: %s" % sectiontype)
            bScanStatus = 91
        # Stop scanner on error
        if bScanStatus >= 90:
            return
        Log.Debug("*******  Ending backgroundScanThread  ***********")
        bScanStatus = 2
        return
    except Exception, e:
        Log.Exception(
            "Exception happened in backgroundScanThread was %s" % str(e))
        bScanStatus = 99
        raise
        Log.Debug("*******  Ending backgroundScanThread  ***********")


@route(PREFIX + '/scanMovieDB')
def scanMovieDB(myMediaURL, outFile, level=None):
    ''' This function will scan a movie section. '''
    Log.Debug("*** Starting scanMovieDB with an URL of %s ***" % myMediaURL)
    Log.Debug('Movie Export level is %s' % level)
    global bScanStatusCount
    global bScanStatusCountOf
    global bScanStatus
    bScanStatusCount = 0
    bScanStatusCountOf = 0
    iCurrent = 0
    try:
        # rows = movies.getMovieHeader(level)
        Log.Debug("About to open file %s" % outFile)
        output.createHeader(outFile=outFile, sectionType='movies', level=level)
        if level in moviefields.singleCall:
            bExtraInfo = False
        else:
            bExtraInfo = True
        while True:
            Log.Debug("Walking medias")
            fetchURL = ''.join((
                myMediaURL,
                '?X-Plex-Container-Start=',
                str(iCurrent),
                '&X-Plex-Container-Size=',
                str(CONTAINERSIZEMOVIES)))
            if level in moviefields.playCountCall:
                fetchURL = ''.join((
                    fetchURL,
                    PLAYCOUNTEXCLUDE,
                    '&type=1'))
            iCount = bScanStatusCount
            partMedias = XML.ElementFromURL(
                fetchURL,
                timeout=float(PMSTIMEOUT))
            if bScanStatusCount == 0:
                bScanStatusCountOf = partMedias.get('totalSize')
                output.setMax(int(bScanStatusCountOf))
                Log.Debug(
                    'Amount of items in this section is %s' %
                    bScanStatusCountOf)
            # HERE WE DO STUFF
            Log.Debug("Retrieved part of medias okay [%s of %s]" % (
                str(bScanStatusCount),
                str(bScanStatusCountOf)))
            medias = partMedias.xpath('.//Video')
            for media in medias:
                myRow = {}
                if level in moviefields.playCountCall:
                    if level == 'PlayCount 1':
                        fieldlist = moviefields.PlayCount_1
                    myRow = misc.getPlayCountLevel(
                        myMedia=media, fieldlist=fieldlist)
                else:
                    # Was extra info needed here?
                    if bExtraInfo:
                        myExtendedInfoURL = genParam(
                            ''.join((
                                misc.GetLoopBack(),
                                '/library/metadata/',
                                misc.GetRegInfo(
                                    media,
                                    'ratingKey')
                                ))
                            )
                        media = XML.ElementFromURL(
                            myExtendedInfoURL,
                            timeout=float(PMSTIMEOUT)).xpath('//Video')[0]
                    # Export the info
                    myRow = movies.getMovieInfo(media, myRow, prefsLevel=level)
                output.writerow(myRow)
                iCurrent += 1
                bScanStatusCount += 1
                Log.Debug("Media #%s from database: '%s'" % (
                    str(iCurrent),
                    misc.GetRegInfo(media, 'title')))
            # Got to the end of the line?
            if int(partMedias.get('size')) == 0:
                break
            if bScanStatus == 3:
                break
            # Keep Alive ping to PMS
            HTTP.Request(
                misc.GetLoopBack() + PREFIX + '/:/prefs',
                cacheTime=0,
                immediate=True)
        output.closefile()
    except ValueError, Argument:
        Log.Critical('Unknown error in scanMovieDb %s' % Argument)
        bScanStatus = 99
        raise
    Log.Debug("******* Ending scanMovieDB ***********")


@route(PREFIX + '/scanShowDB')
def scanShowDB(myMediaURL, outFile, level=None, key=None):
    ''' This function will scan a TV-Show section '''
    Log.Debug(''.join((
        '******* Starting scanShowDB with',
        ' an URL of % s ***********' % myMediaURL)))
    global bScanStatusCount
    global bScanStatusCountOf
    global bScanStatus
    bScanStatusCount = 0
    bScanStatusCountOf = 0
    try:
        Log.Debug("About to open file %s" % outFile)
        output.createHeader(
            outFile=outFile, sectionType='tvseries', level=level)
        if level in tvfields.singleCall:
            bExtraInfo = False
        else:
            bExtraInfo = True
        Log.Debug('Starting to fetch the list of items in this section')
        while True:
            Log.Debug("Walking medias")
            iCount = bScanStatusCount
            if 'Show Only' in level:
                fetchURL = ''.join((
                    myMediaURL,
                    '?X-Plex-Container-Start=',
                    str(iCount),
                    '&X-Plex-Container-Size=1'))
            else:
                fetchURL = ''.join((
                    myMediaURL,
                    '?X-Plex-Container-Start=',
                    str(iCount),
                    '&X-Plex-Container-Size=',
                    str(CONTAINERSIZETV)))
            if level in tvfields.playCountCall:
                fetchURL = ''.join((
                    fetchURL,
                    PLAYCOUNTEXCLUDE,
                    '&type=4'))
            partMedias = XML.ElementFromURL(
                fetchURL,
                timeout=float(PMSTIMEOUT))
            if bScanStatusCount == 0:
                bScanStatusCountOf = partMedias.get('totalSize')
                output.setMax(int(bScanStatusCountOf))
                Log.Debug(''.join((
                    'Amount of items in this section is ',
                    '%s' % bScanStatusCountOf)))
            # HERE WE DO STUFF
            Log.Debug("Retrieved part of medias okay [%s of %s]" % (
                str(iCount), str(bScanStatusCountOf)))
            for TVShow in partMedias:
                bScanStatusCount += 1
                iCount += 1
                ratingKey = TVShow.get("ratingKey")
                title = TVShow.get("title")
                if 'Show Only' in level:
                    myRow = {}
                    # Export the info
                    myRow = tvseries.getShowOnly(
                        TVShow,
                        myRow,
                        level)
                    try:
                        output.writerow(myRow)
                    except Exception, e:
                        Log.Exception(
                            'Exception happend in ScanShowDB: %s' % str(e))
                    continue
                elif level in tvfields.playCountCall:
                    if level == 'PlayCount 1':
                        fieldlist = tvfields.PlayCount_1
                    myRow = misc.getPlayCountLevel(
                        myMedia=TVShow, fieldlist=fieldlist)
                    try:
                        output.writerow(myRow)
                    except Exception, e:
                        Log.Exception(
                            'Exception happend in ScanShowDB: %s' % str(e))
                    continue
                else:
                    if level in [
                            'Level 2',
                            'Level 3',
                            'Level 4',
                            'Level 5',
                            'Level 6',
                            'Level 7',
                            'Level 8',
                            'Level 666']:
                        myURL = ''.join((
                            misc.GetLoopBack(),
                            '/library/metadata/',
                            ratingKey))
                        tvSeriesInfo = XML.ElementFromURL(
                            myURL,
                            timeout=float(PMSTIMEOUT))
                        # Getting stuff from the main TV-Show page
                        # Grab collections
                        serieInfo = tvSeriesInfo.xpath(
                            '//Directory/Collection')
                        myCol = ''
                        for collection in serieInfo:
                            if myCol == '':
                                myCol = collection.get('tag')
                            else:
                                myCol = ''.join((
                                    myCol,
                                    Prefs['Seperator'],
                                    collection.get('tag')))
                        if myCol == '':
                            myCol = 'N/A'
                        # Grab locked fields
                        serieInfo = tvSeriesInfo.xpath('//Directory/Field')
                        myField = ''
                        for Field in serieInfo:
                            if myField == '':
                                myField = Field.get('name')
                            else:
                                myField = ''.join((
                                    myField,
                                    Prefs['Seperator'],
                                    Field.get('name')))
                        if myField == '':
                            myField = 'N/A'
                    # Get size of TV-Show
                    episodeTotalSize = XML.ElementFromURL(
                        ''.join((
                            misc.GetLoopBack(),
                            '/library/metadata/',
                            ratingKey,
                            '/allLeaves?X-Plex-Container-',
                            'Start=0&X-Plex-Container-Size=0')),
                        timeout=float(PMSTIMEOUT)).xpath('@totalSize')[0]
                    Log.Debug('Show: %s has %s episodes' % (
                        title,
                        episodeTotalSize))
                    episodeCounter = 0
                    baseURL = ''.join((
                        misc.GetLoopBack(),
                        '/library/metadata/',
                        ratingKey,
                        '/allLeaves'))
                    while True:
                        myURL = ''.join((
                            baseURL,
                            '?X-Plex-Container-Start=',
                            str(episodeCounter),
                            '&X-Plex-Container-Size=',
                            str(CONTAINERSIZEEPISODES)))
                        strLog = ''.join((
                            'Show %s of ' % (iCount),
                            '%s with a RatingKey of ' % (bScanStatusCountOf),
                            '%s at myURL: ' % (ratingKey),
                            '%s with a title of "%s" ' % (myURL, title),
                            'episode %s ' % (episodeCounter),
                            'of %s' % (episodeTotalSize)
                        ))
                        Log.Debug(strLog)
                        MainEpisodes = XML.ElementFromURL(
                            myURL,
                            timeout=float(PMSTIMEOUT))
                        Episodes = MainEpisodes.xpath('//Video')
                        for Episode in Episodes:
                            myRow = {}
                            # Was extra info needed here?
                            if bExtraInfo:
                                strUrl = ''.join((
                                    misc.GetLoopBack(),
                                    '/library/metadata/',
                                    misc.GetRegInfo(Episode, 'ratingKey')
                                ))
                                myExtendedInfoURL = genParam(strUrl)
                                Episode = XML.ElementFromURL(
                                    myExtendedInfoURL,
                                    timeout=float(
                                        PMSTIMEOUT)).xpath('//Video')[0]
                            # Export the info
                            myRow = tvseries.getTvInfo(
                                Episode, myRow, level=level)
                            if level in [
                                    'Level 2',
                                    'Level 3',
                                    'Level 4',
                                    'Level 5',
                                    'Level 6',
                                    'Level 7',
                                    'Level 8',
                                    'Level 666']:
                                myRow['Collection'] = myCol
                                myRow['Locked Fields'] = myField
                            output.writerow(myRow)
                        episodeCounter += CONTAINERSIZEEPISODES
                        if episodeCounter > int(episodeTotalSize):
                            break
            # KeepAlive ping to PMS
            HTTP.Request(
                misc.GetLoopBack() + PREFIX + '/:/prefs',
                cacheTime=0,
                immediate=True)
            # Got to the end of the line?
            if int(partMedias.get('size')) == 0:
                break
        output.closefile()
    except ValueError as err:
        Log.Exception('Exception happend as %s' % err.args)
    Log.Debug("******* Ending scanShowDB ***********")


@route(PREFIX + '/selectPList')
def selectPList():
    ''' This function will show a menu with playlists '''
    Log.Debug("User selected to export a playlist")
    # Abort if set to auto path
    if Prefs['Auto_Path']:
        message = ''.join((
            "Playlists can not be exported when path is set",
            " to auto. You need to specify a manual path in the prefs"))
        oc = ObjectContainer(
            title1=''.join((
                "Error!. Playlists can not be exported ",
                "when path is set to auto.",
                " You need to specify a manual path in the prefs")),
            no_cache=True,
            message=message)
        oc.add(
            DirectoryObject(
                key=Callback(MainMenu),
                title="Go to the Main Menu"))
        Log.Debug('Can not continue, since on AutoPath')
        return oc
    # Else build up a menu of the playlists
    oc = ObjectContainer(title1='Select Playlist to export', no_cache=True)
    playlists = XML.ElementFromURL(
        misc.GetLoopBack() + '/playlists/all',
        timeout=float(PMSTIMEOUT)).xpath('//Playlist')
    for playlist in playlists:
        title = playlist.get('title')
        try:
            thumb = misc.GetLoopBack() + playlist.get('composite')
        except Exception, e:
            pass
        playListType = playlist.get('playlistType')
        if playListType in ['video', 'audio', 'photo']:
            key = playlist.get('key')
            strLog = ''.join((
                "Added playlist: ",
                title,
                " to the listing with a key of: ",
                key
            ))
            Log.Debug(strLog)
            oc.add(DirectoryObject(
                key=Callback(
                    backgroundScan,
                    title=playListType,
                    sectiontype='playlists',
                    key=key,
                    random=time.clock()),
                thumb=thumb,
                title='Export from "' + title + '"',
                summary='Export list from "' + title + '"'))
    oc.add(DirectoryObject(
        key=Callback(MainMenu),
        title="Go to the Main Menu"))
    return oc


@route(PREFIX + '/getPListContents')
def scanPList(key, outFile, level=None):
    ''' Here we go for the actual playlist '''
    Log.Debug("******* Starting scanPList with an URL of: %s" % key)
    global bScanStatusCount
    global bScanStatusCountOf
    global bScanStatus
    bScanStatusCount = 0
    try:
        # Get playlist type once more
        playListXML = XML.ElementFromURL(
            key + '?X-Plex-Container-Start=0&X-Plex-Container-Size=0',
            timeout=float(PMSTIMEOUT))
        playListType = playListXML.get('playlistType')
        Log.Debug('Writing headers for Playlist Export')
        output.createHeader(outFile, 'playlist', playListType, level=level)
        bScanStatusCountOf = playListXML.get('leafCount')
        iCount = bScanStatusCount
        output.setMax(int(bScanStatusCountOf))
        Log.Debug('Starting to fetch the list of items in this section')
        myRow = {}
        if playListType == 'video':
            playListItems = XML.ElementFromURL(
                key,
                timeout=float(PMSTIMEOUT)).xpath('//Video')
        elif playListType == 'audio':
            playListItems = XML.ElementFromURL(
                key,
                timeout=float(PMSTIMEOUT)).xpath('//Track')
        elif playListType == 'photo':
            playListItems = XML.ElementFromURL(
                key,
                timeout=float(PMSTIMEOUT)).xpath('//Photo')
        for playListItem in playListItems:
            playlists.getPlayListInfo(
                playListItem,
                myRow,
                playListType,
                level=level)
            output.writerow(myRow)
        output.closefile()
    except Exception, e:
        Log.Critical("Detected an exception in scanPList")
        bScanStatus = 99
        # Dumps the error so you can see what the problem is
        raise
    message = 'All done'
    oc = ObjectContainer(title1='Playlists', no_cache=True, message=message)
    oc.add(
        DirectoryObject(
            key=Callback(MainMenu),
            title="Go to the Main Menu"))
    Log.Debug("******* Ending scanPListDB ***********")
    return oc


@route(PREFIX + '/scanArtistDB')
def scanArtistDB(myMediaURL, outFile, level=None):
    ''' This function will scan a Music section.'''
    Log.Debug(
        "*** Starting scanArtistDB with an URL of %s ***" % myMediaURL)
    global bScanStatusCount
    global bScanStatusCountOf
    global bScanStatus
    bScanStatusCount = 0
    try:
        Log.Debug('Writing headers for Audio Export')
        output.createHeader(outFile=outFile, sectionType='audio', level=level)
        if level in audiofields.singleCall:
            bExtraInfo = False
        else:
            bExtraInfo = True
        Log.Debug('Starting to fetch the list of items in this section')
        fetchURL = ''.join((
            myMediaURL,
            '?type=10&X-Plex-Container-Start=',
            str(bScanStatusCount),
            '&X-Plex-Container-Size=0'))
        medias = XML.ElementFromURL(fetchURL, timeout=float(PMSTIMEOUT))
        if bScanStatusCount == 0:
            bScanStatusCountOf = medias.get('totalSize')
            output.setMax(int(bScanStatusCountOf))
            Log.Debug(
                'Amount of items in this section is %s' % bScanStatusCountOf)
        Log.Debug("Walking medias")
        while True:
            fetchURL = ''.join((
                myMediaURL,
                '?type=10&sort=artist.titleSort,album.titleSort:',
                'asc&X-Plex-Container-Start=',
                str(bScanStatusCount),
                '&X-Plex-Container-Size=',
                str(CONTAINERSIZEAUDIO)))
            medias = XML.ElementFromURL(fetchURL, timeout=float(PMSTIMEOUT))
            if medias.get('size') == '0':
                break
            # HERE WE DO STUFF
            tracks = medias.xpath('.//Track')
            for track in tracks:
                bScanStatusCount += 1
                # Get the Audio Info
                myRow = {}
                # Was extra info needed here?
                if bExtraInfo:
                    myExtendedInfoURL = genParam(
                        ''.join((
                            misc.GetLoopBack(),
                            '/library/metadata/',
                            misc.GetRegInfo(track, 'ratingKey'))))
                    track = XML.ElementFromURL(
                        myExtendedInfoURL,
                        timeout=float(PMSTIMEOUT)).xpath('//Track')[0]
                audio.getAudioInfo(track, myRow, level=level)
                output.writerow(myRow)
            HTTP.Request(
                misc.GetLoopBack() + PREFIX + '/:/prefs',
                cacheTime=0,
                immediate=True)
        output.closefile()
    except Exception, e:
        Log.Exception("Detected an exception in scanArtistDB as: %s" % str(e))
        bScanStatus = 99
        # Dumps the error so you can see what the problem is
        raise
    Log.Debug("******* Ending scanArtistDB ***********")


@route(PREFIX + '/scanPhotoDB')
def scanPhotoDB(myMediaURL, outFile, level=None):
    ''' This function will scan a Photo section. '''
    Log.Debug("*** Starting scanPhotoDB with an URL of %s ***" % myMediaURL)
    global bScanStatusCount
    global bScanStatusCountOf
    global bScanStatus
    bScanStatusCount = 0
    iLocalCounter = 0
    try:
        mySepChar = Prefs['Seperator']
        Log.Debug('Writing headers for Photo Export')
        output.createHeader(outFile=outFile, sectionType='photo', level=level)
        if level in photofields.singleCall:
            bExtraInfo = False
        else:
            bExtraInfo = True
        Log.Debug('Starting to fetch the list of items in this section')
        fetchURL = ''.join((
            myMediaURL,
            '?type=10&X-Plex-Container-Start=',
            str(iLocalCounter),
            '&X-Plex-Container-Size=0'))
        medias = XML.ElementFromURL(fetchURL, timeout=float(PMSTIMEOUT))
        bScanStatusCountOf = 'N/A'
        output.setMax(int(0))
        Log.Debug("Walking medias")
        while True:
            fetchURL = ''.join((
                myMediaURL,
                '?X-Plex-Container-Start=',
                str(iLocalCounter),
                '&X-Plex-Container-Size=',
                str(CONTAINERSIZEPHOTO)))
            medias = XML.ElementFromURL(fetchURL, timeout=float(PMSTIMEOUT))
            if medias.get('size') == '0':
                break
            getPhotoItems(medias=medias, bExtraInfo=bExtraInfo, level=level)
            iLocalCounter += int(CONTAINERSIZEPHOTO)
        output.closefile()
    except Exception, e:
        Log.Critical("Detected an exception in scanPhotoDB")
        bScanStatus = 99
        # Dumps the error so you can see what the problem is
        raise
    Log.Debug("******* Ending scanPhotoDB ***********")
    return


@route(PREFIX + '/getPhotoItems')
def getPhotoItems(medias, bExtraInfo, level=None):
    ''' This function will walk directories in a photo section '''
    global bScanStatusCount
    try:
        # Start by grapping pictures here
        et = medias.xpath('.//Photo')
        for element in et:
            myRow = {}
            myRow = photo.getInfo(element, myRow, level=level)
            bScanStatusCount += 1
            output.writerow(myRow)
        # Elements that are directories
        et = medias.xpath('.//Directory')
        for element in et:
            myExtendedInfoURL = genParam(
                misc.GetLoopBack() + element.get('key'))
            # TODO: Make small steps here when req. photos
            elements = XML.ElementFromURL(
                myExtendedInfoURL,
                timeout=float(PMSTIMEOUT))
            getPhotoItems(medias=elements, bExtraInfo=bExtraInfo, level=level)
    except Exception, e:
        Log.Debug('Exception in getPhotoItems was %s' % str(e))
        pass


@route(PREFIX + '/logSettings')
def logSettings():
    """ Here we dump current settings to the log file """
    itemsPrefs = [
        'Output_Format',
        'Autosize_Column',
        'Autosize_Row',
        'Export_Posters',
        'Poster_Hight',
        'Poster_Width',
        'Export_Path',
        'Auto_Path',
        'Delimiter',
        'Line_Wrap',
        'Line_Length',
        'Seperator',
        'Sort_title',
        'Original_Title',
        'Movie_Level',
        'TV_Level',
        'Artist_Level',
        'Photo_Level',
        'PlayList_Level',
        'mu_Level',
        'Check_Files']
    Log.Info('**************** Settings ****************')
    for item in itemsPrefs:
        Log.Info('Setting %s set to: %s' % (item, str(Prefs[item])))
    Log.Info('************* Settings ended *************')
