'''
title:    gpu_d.py
version:  0.1n
released: 12/12/13
author:   Dagorath
purpose:  - Regulate NVIDIA video card fan speed to keep GPU temperature close to a user defined
            target temperature (units are Celsius). The script is essentially a frontend for the nvidia-settings
            binary supplied with nVIDIA's drivers for Linux. See "man nvidia-settings" for details. 
            
          - Provide info re: GPU resource utilization, clock frequency, fan speed and various others
prerequisites:

            1)  An /etc/X11/xorg.conf that contains a syntactically corrrect Coolbits 4 (or 5) entry
                (something like "nvidia-config coolbits 4" mods the xorg.conf properly)
            2)  An nVIDIA video card and properly installed driver, the nvidia-settings binary
                has remained virtually unchanged through several driver updates and probably
                won't change substantially
            3)  Developed and tested on Python 2.7.3. Might run on Python 3.x as is, will definitely run on
                3.x with minor syntax changes.
            4)  wmctrl - Linux binary to control terminal window dimensions, on Debian based syatems install with
                sudo apt-get install wmctrl
to do:

            1)  Discover how to unlock the GPU clocks. Being able to reduce clock speed would make it
                possible to stay close to the target temperature while keeping the fan speed below a
                user specified limit.
            2)  An optional audio warning if temperature exceeds target for prolonged period
            3)  An auto-suspend-GPU crunching function if temperature remains above target while actual fan speed (RPM)
                remains ridiculously low for prolonged period which would indicate failed or failing fan
            4)  A quiet mode option that produces no screen output to reduce overhead, suitable for running in background
            5)  I'm not sure but the nvidia-settings binary args syntax suggests it _might_ have the ability to get/set
                params on remote cards. That would be awesome. If that ability doesn't exist then consider implementing an
                RPC interface similar to BOINC's, quite doable with Python thoughy I'm not sure how robust it would be.  
              
'''

from __future__ import division
from time import sleep
from subprocess import check_output
from sys import argv
from os import system
from os.path import exists
import curses
from curses import panel

# #######################  an incomplete list of constants we will use   ################################
global snooze, fan_speed_up_lim, fan_speed_low_lim, tolerance, nap_msec, stdscr, title
global x_pix, y_pix, p2_cols, p2_rows
snooze = 5                  # units = seconds, main loop delay,   

                            # All fan speed assignments are percents in range 1 to 100.  
                            # Values outside that range result in nvidia-settings returning
                            # stuff we don't need/want to deal with so KISS.
fan_speed_up_lim = 80       # As of driver ver. 331.17 the upper fan speed limit is 80%
                            # any speed assignment > 80% is ignored hence this upper bound.

fan_speed_low_lim = 60      # This is a safety precaution. This script could fail without warning
                            # so we should NEVER set the fan speed below a minimal speed that 
                            # is guaranteed to keep the GPU reasonably cool. On my system that speed
                            # is 60%. Need a way to establish a sensible low limit on any system. 
                                                          
tolerance = 1               # The amount above or below the target_temp we will tolerate
                            # without taking corrective action.

nap_msec = 1                # Millisecs to wait in the "get input" function, wait_a_while()

stdscr = 1                  # Not sure what this does but the example code I learned from uses it
                            # to specify, I think, the curses panel that is currently in focus?

title = '\n ' + '='*40 + '\n' + ' | Dag\'s nVidia GPU temperature monitor |' + '\n ' + '='*40 + '\n'

x_pix = '475'               # default width of terminal window in pixels, can specify on command line

y_pix = '340'               # default height of terminal window in pixels, can specify onm command line

x_loc = '1600'               # default horizontal coordinate of upper left corner of terminal window in pixels

y_loc = '1'               # default vertical coordinate of upper left corner of terminal window in pixels    

p2_cols = 52                # text columns in curses panel p2

p2_rows = 18                # text rows in curses panel p2

# #######################  list of global vars, probably incomplete too ###############################

global target_temp, current_speed, previous_temp, temp_delta

target_temp = 0             # The temperature use wants to maintain, specified on command line

current_speed = 0           # Current fan speed

previous_temp = 0           # The GPU temperature read in the previous iteration of the while loop

temp_delta = 0              # The difference between the current GPU temp and the previous temp

rpm = '0'                   # Fan rpm 
 
# #########################################################################################
# ----------------------------------------------------------------------------------------
def wGetchar(win = None):
    if win is None: win = stdscr
    return win.getch()
# ----------------------------------------------------------------------------------------
def Getchar():
    wGetchar()
# ----------------------------------------------------------------------------------------
def wait_a_while():
    if nap_msec == 1:
        return Getchar()
    else:
        curses.napms(nap_msec)
# ----------------------------------------------------------------------------------------
def saywhat(text):
    stdscr.move(curses.LINES - 1, 0)
    stdscr.clrtoeol()
    stdscr.addstr(text)
# ----------------------------------------------------------------------------------------
def mkpanel(color, rows, cols, tly, tlx):
    win = curses.newwin(rows, cols, tly, tlx)
    pan = panel.new_panel(win)
    if curses.has_colors():
        if color == curses.COLOR_BLUE:
            fg = curses.COLOR_WHITE
        else:        
            fg = curses.COLOR_BLACK
        bg = color
        curses.init_pair(color, fg, bg)
        win.bkgdset(ord(' '), curses.color_pair(color))
    else:
        win.bkgdset(ord(' '), curses.A_BOLD)

    return pan
# ----------------------------------------------------------------------------------------
def pflush():
    panel.update_panels()
    curses.doupdate()
# ----------------------------------------------------------------------------------------
def put_text(win, row, col, text, clr):
    win.move(row, col)
    win.addstr(text)
    if clr: win.clrtoeol()
# ----------------------------------------------------------------------------------------
def monitor(win):
    global stdscr, nap_msec, target_temp, current_speed, previous_temp, temp_delta, rpm
    stdscr = win
    nap_msec = 1
    stdscr.nodelay(1)
    stdscr.refresh()

    '''p1 = mkpanel(curses.COLOR_RED, 3, 40, 0, 0)
    p1.set_userptr('p1')
    p1.window().move(1, 1)
    p1.window().addstr(' Dag\'s nVIDIA GPU temperature monitor')
    p1.window().clrtoeol()
    #s = " Dag's nVIDIA GPU temperature monitor"
    #fill_panel(p1, s)
    p1.window().box() '''

    p2 = mkpanel(curses.COLOR_BLUE, p2_rows, p2_cols, 0, 0)
    p2.set_userptr('p2')
    win = p2.window()
    
    # print static text in p2 (panel 2), this text never changes so we print it onc here outside the main 
    # work loop, text that changes periodically is of course printed inside the main loop below
    col1 = 1
    put_text(win, 1, col1, 'Utilization (%)     PCIe', True)
    put_text(win, 2, col1, '   cpu:                generation:       ' + get_nvidia_info('PCIEGen'), True)
    put_text(win, 3, col1, '   graphics:           max. link width:  ' + get_nvidia_info('PCIEMaxLinkWidth'), True)
    put_text(win, 4, col1, '   memory:             curr. link width: ' + get_nvidia_info('PCIECurrentLinkWidth'), True)
    put_text(win, 5, col1, '   video:              max. link speed:  ' + str(round(int(get_nvidia_info('PCIEMaxLinkSpeed')) / 1000, 2)) + ' GT/s', True)
    put_text(win, 6, col1, '   PCIe:               curr. link speed: ' + str(round(int(get_nvidia_info('PCIECurrentLinkSpeed')) / 1000, 2)) + ' GT/s', True)
    put_text(win, 7, col1, 'Temperature (C)     Clocks', True)
    put_text(win, 8, col1, '   target:             graphics:', True)
    put_text(win, 9, col1, '   current:            memory:', True)
    put_text(win, 10, col1, '   delta:           Ram', True)
    put_text(win, 11, col1, 'Fan speed              total:     ' + get_gpu_info('TotalDedicatedGPUMemory'), True)
    put_text(win, 12, col1, '   current:            used:' , True)
    put_text(win, 13, col1, '   delta:           CUDA cores:   ' + get_gpu_info('CUDACores'), True)
    put_text(win, 14, col1, '   rpm:             Driver:       ' + get_nvidia_info('NvidiaDriverVersion'), False)
    put_text(win, 15, col1, ' ', True)

    '''col1 = 22
    put_text(win, 1, col1, 'PCIem')
    put_text(win, 2, col1, '   generation:')
    put_text(win, 3, col1, '   speed:')
    put_text(win, 4, col1, '   link width:')
    put_text(win, 5, col2, '    video:')
    put_text(win, 6, col2, '    PCIe:')
    put_text(win, 7, col2, ' Temperature (C)')
    put_text(win, 8, col2, '    target:')
    put_text(win, 9, col2, '    current:')
    put_text(win, 10, col2, '    delta:')
    put_text(win, 11, col2, ' Fan speed')
    put_text(win, 12, col2, '    current %:')
    put_text(win, 13, col2, '    delta %:')
    put_text(win, 14, col2, '    rpm:')'''
    win.box()

    #pflush()


    # The main work loop, iterates until user presses q at which time the script exits.
    # At this time user input other than q is ignored.
                
    # The way it works is simple. We read the current temp, if it's not between acceptable
    # limits (the target temp specified on the command line +/- 1) we take corrective action
    # unless the temp_delta indicates the temperature is already going in the desired direction.
    # Without tracking and using temp_delta the NTSNWB (not too sophisticated, never will be)
    # algorithm tends to over-correct which can produce wild and unnecessary swings in fan speed
    # due to temperature<->(cooling effect) hysteresis I guess. 

    while 1:
        x = get_utilization().split(',')
        current_temp = get_temp()
        temp_delta = current_temp - previous_temp
        new_speed = current_speed
            
        if current_temp > target_temp + tolerance:
            if temp_delta > -1:
                # temp either did not change or it increased, attempt correction
                new_speed = current_speed + (current_temp - target_temp)
                if new_speed > 80:
                    new_speed = 80
                                         
        elif current_temp < target_temp - tolerance:
            if temp_delta < 1:
                # temp either did not change or it decreased, attempt correction
                new_speed = chek_new_speed(current_speed - (target_temp - current_temp))

        freqs = get_gpu_info('GPUCurrentClockFreqs').split(',')

        col1, col2 = 14, 35
        put_text(win, 2, col1, '99', False)
        put_text(win, 3, col1, x[0].split()[1], False)
        put_text(win, 4, col1, x[1].split()[1], False)
        put_text(win, 5, col1, x[2].split()[1], False)
        put_text(win, 6, col1, x[3].split()[1], False)
        put_text(win, 8, col1, str(target_temp), False)
        put_text(win, 9, col1, str(current_temp), False)
        put_text(win, 10, col1, str(temp_delta) + '  ', False)
        put_text(win, 12, col1, str(current_speed), False)
        put_text(win, 13, col1, str(new_speed - current_speed) + '  ', False)
        put_text(win, 14, col1, get_rpm() + 'v ', False)

        put_text(win, 8, col2, freqs[0], False)
        put_text(win, 9, col2, freqs[1], False)
        put_text(win, 12, col2, get_gpu_info('UsedDedicatedGPUMemory'), False)
        put_text(win, 12, col2, get_gpu_info('UsedDedicatedGPUMemory'), False)
        put_text(win, 12, col2, get_gpu_info('UsedDedicatedGPUMemory'), False)
        # GPUCurrentClockFreqsString
        
        #put_text(win, 13, col2, get_gpu_info('CUDACores'), False)
        put_text(win, 15, 1, ' ', True)
        put_text(win, 16, 1, 'Press q to exit', True)

        '''put_text(win, 2, col2, 'PCIe')
        put_text(win, 3, col2, x[0].split()[1])
        put_text(win, 4, col1, x[1].split()[1])
        put_text(win, 5, col1, x[2].split()[1])
        put_text(win, 6, col1, x[3].split()[1])
        put_text(win, 8, col1, str(target_temp))
        put_text(win, 9, col1, str(current_temp))
        put_text(win, 10, col1, str(temp_delta))
        put_text(win, 12, col1, str(current_speed))
        put_text(win, 13, col1, str(new_speed - current_speed))
        put_text(win, 14, col1, get_rpm())
        put_text(win, 15, 1, ' ')'''
        win.box()

        pflush()
        #p1.window().refresh()
        current_speed = set_speed(new_speed)
        previous_temp = current_temp

        count = 0
        while count < 5:
            if stdscr.getch() == ord('q'): return() 
            else:
                sleep (1)
                count += 1
        #if wait_a_while() == 'q': exit()
        #if Getchar() == 'q': exit()

# ----------------------------------------------------------------------------------------
def get_nvidia_info(query):
    return check_output(['nvidia-settings', '--query', 'localhost:0.0/' + query, '-t'])
# ----------------------------------------------------------------------------------------
def get_gpu_info(query):
    return check_output(['nvidia-settings', '--query', 'localhost:0[gpu:0]/' + query, '-t'])
# ----------------------------------------------------------------------------------------
def get_utilization():
    # returns a string of 4 numbers that are percentages : graphics, memory, video, PCIe
    x = check_output(['nvidia-settings', '--query', 'localhost:0[gpu:0]/GPUUtilization', '-t']).strip().replace(' ', '').replace('=', ': ')
    #print 'x:', x
    #print 'x split:', x.split(',')
    #for i in range(3):
    #    x[i].replace('=', ': ')
    return x
# ----------------------------------------------------------------------------------------
def set_speed(speed):
    x = check_output(['nvidia-settings', '--assign', 'localhost:0[fan:0]/GPUCurrentFanSpeed=' + str(speed), '-t'])
    return (int(x[x.rfind(' ') + 1:x.rfind('.')]))  # return current fan speed
# ----------------------------------------------------------------------------------------    
def get_temp():
    return (int(check_output(['nvidia-settings', '--query', 'localhost:0[thermalsensor:0]/ThermalSensorReading', '-t'])))
# ----------------------------------------------------------------------------------------
def get_rpm():
    return check_output(['nvidia-settings', '--query', 'localhost:0[fan:0]/GPUCurrentFanSpeedRPM', '-t'])        
# ----------------------------------------------------------------------------------------
def chek_new_speed(speed):
    # speed must be between 1 and 100 else set_speed() crashes
    if speed > fan_speed_up_lim: return(fan_speed_up_lim) 
    elif speed < fan_speed_low_lim: return (fan_speed_low_lim)
    else: return (speed)
# ----------------------------------------------------------------------------------------    
def safe_exit(err_code):
    # set fan speed to max, return fan speed control to auto state, exit
    set_speed(fan_speed_up_lim)
    s = check_output(['nvidia-settings', '--assign', 'localhost:0[gpu:0]/GPUFanControlState=0'])
    exit (err_code)
# ----------------------------------------------------------------------------------------    
def print_usage():
    print'\n#######################################################################################\n'
    print 'Usage:'
    print '   python nvidiatmon.py target_temp width height' 
    print
    print '   where: target_temp = an integer, the temperature at which you want your GPU to run'
    print '          width = an integer, the desired width of the terminal window in pixels'
    print '          height = an integer, the desired height of the terminal window in pixels'
    print
    print 'Example:'
    print '   python nvidiatmon.py 70 475 340'
    print '\nNote:'
    print '   If the width or height parameter is too small the script will crash. The values of'
    print '   475 and 300 work for my screen resolution but not necessarily yours. If in doubt'
    print '   try large values like 1,000 and 1,000 which will likely be too big but at least it'
    print '   won\'t crash. The window need be no bigger than the blue panel. If it is then'
    print '   decrease the width and height until it fits without crashing and use those values'
    print '   in an invocating script or just remember them.'   
    print '\n######################################################################################\n'
# -----------------------------------------------------------------------------------------
def print_disclaimer():
    print 'Disclaimer:'
    print 
    print 'The author of this software has taken precautions to help prevent your'
    print 'GPU from overheating. The primary precaution is that the software is '
    print 'designed to never reduce the fan speed below a reasonable limit in case'
    print 'the software should fail and leave the fan speed at a dangerously low'
    print 'level.'
    print
    print 'By running this software you agree that the author, Dagorath, is not'
    print 'liable for any damage to your GPU or to your computer caused by this'
    print 'software or failure of this software.'
    print
    s = raw_input('Enter C or c to continue, X or x to exit: ')

    if not s == 'C' and not s == 'c':
        exit(0) 
# ---------------------------------------------------------------------------------------- 
        
# ###############################    "main()" starts here    ############################

print title
print
if not exists('/usr/bin/wmctrl'):
    #print 'Package "wmctrl" is not installed. Please execute "sudo apt-get install wmctrl"'
    if raw_input('Package "wmctrl" is not installed.\nDo you wish to install it now? (y/n) ').lower() == 'y':
        x = check_output(['sudo', 'apt-get', '-y', 'install', 'wmctrl'])
    else:
        exit(1) 

# check command line args
if len(argv) < 2:
    print_usage()
    exit(1)

if argv[1].isdigit():
    target_temp = int(argv[1])
else:
    print_usage()
    exit(1)

#if len(argv) == 3 and (not argv[2] == 'C' and not argv[2] == 'c'):
#        print_disclaimer()

if argv[2].isdigit():
    x_pix = int(argv[2])
else: 
    print_usage()
    exit(1)

if argv[3].isdigit():
    y_pix = int(argv[3])
else: 
    print_usage()
    exit(1)
        
if target_temp > 85:
    print 'Target temperature ' + str(target_temp) + ' Celsius is too high. Please choose a lower target temperature, exiting.'
    print
    exit(1)

# inputs seem OK, try switch to manual fan speed control mode
s = check_output(['nvidia-settings', '--assign', 'localhost:0[gpu:0]/GPUFanControlState=1'])

# check if fan speed control is in manual mode 
s = check_output(['nvidia-settings', '--query', 'localhost:0[gpu:0]/GPUFanControlState', '--terse'])
s = s.strip('\n').strip(' ')

if not s == '1':
    print 'ERROR: failed switch to manual fan speed control mode, exiting.'
    safe_exit(1)
    print
else:
    current_speed = set_speed(70)
    previous_temp = get_temp()
    temp_delta = 0
    x = check_output(['wmctrl', '-r', ':ACTIVE:', '-e', '0,' + str(x_loc) + ',' + str(y_loc) + ',' + str(x_pix) + ',' + str(y_pix)])
    x = check_output(['wmctrl', '-r', ':ACTIVE:', '-T', 'Dag\'s not too fancy NVIDIA temperature monitor']) 
    curses.wrapper(monitor)
