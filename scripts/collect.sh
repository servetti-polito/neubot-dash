#!/bin/sh

#
# Copyright (c) 2012 Simone Basso <bassosimone@gmail.com>,
#  NEXA Center for Internet & Society at Politecnico di Torino
#
# This file is part of Neubot <http://www.neubot.org/>.
#
# Neubot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Neubot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Neubot.  If not, see <http://www.gnu.org/licenses/>.
#

#
# Helper script to collect Neubot results from remote servers
# and to publish it on some HTTP or FTP location.
# Optionally anonymize results that do not contain the permission
# to publish.  This should not happen for newer clients but may
# be the case with before 0.4.6 clients.
#

#
# Periodically invoke this command to fetch new results from
# neubot servers and copy them on your local machine.
# Ideally, this script should be in cron(1) and should run
# everyday and sync the local results copy.
# This is just a convenience wrapper around rsync and it sets
# the maximum bandwidth to a reasonable value to avoid hogging
# resources on the measurement server.
#
pull()
{
    localdir="master.neubot.org"
    remote="master.neubot.org:/var/lib/neubot/*"

    options=$(getopt d:nR:v $*)
    if [ $? -ne 0 ]; then
        echo "Usage: pull [-nv] [-d localdir] [-R remote]" 2>&1
        echo "Default remote: $remote" 2>&1
        echo "Default localdir: $localdir" 2>&1
        exit 1
    fi

    set -- $options

    # Do not tollerate errors
    set -e

    while [ $# -ge 0 ]; do
        if [ "$1" = "-d" ]; then
            localdir=$2
            shift
            shift
        elif [ "$1" = "-n" ]; then
            flags="$flags -n"
            shift
        elif [ "$1" = "-R" ]; then
            remote=$2
            shift
            shift
        elif [ "$1" = "-v" ]; then
            flags="$flags -v"
            shift
        elif [ "$1" = "--" ]; then
            shift
            break
        fi
    done

    rsync -rt --bwlimit=512 $flags $remote $localdir
}

#
# This is just a convenience command that is invoked to
# inspect the content of a result and tell whether we
# can publish it directly or it needs some postprocessing.
# This should not happen for new versions of Neubot but
# there is a shrinking number of old clients around.
# Here we use Python because it is a pain to inspect the
# content from the command line.
#
privacy_ok()
{
    python - $* << EOF
import json
import sys

filep = open(sys.argv[1], 'rb')
content = filep.read()
dictionary = json.loads(content)
if (int(dictionary.get('privacy_informed', 0)) == 1 and
    int(dictionary.get('privacy_can_collect', 0)) == 1 and
    int(dictionary.get('privacy_can_publish', 0)) == 1):

    # Privacy is OK
    sys.exit(0)

sys.exit(1)
EOF
}

#
# Package publisheable data into a tarball ready for being
# published on the web.
#
prepare()
{
    log_always=echo
    log_info=:
    log_error=echo

    options=$(getopt v $*)
    if [ $? -ne 0 ]; then
        echo "Usage: prepare [-v] dir..." 2>&1
        exit 1
    fi

    # Do not tollerate errors
    set -e

    set -- $options

    while [ $# -ge 0 ]; do
        if [ "$1" = "-v" ]; then
            log_info=echo
            shift
        elif [ "$1" = "--" ]; then
            shift
            break
        fi
    done

    for rawdir in $*; do

        #
        # Make sure we don't prepare $today for publish because the
        # data collection is not complete for that directory.
        #
        if ls $rawdir|head -n1|grep -q $(date +^%Y%m%d); then
            $log_info "$0: skipping today"
            continue
        fi

        # Parametrize the tarball name so we can change it easily
        tarball=results.tar
        if [ -f $rawdir/$tarball.gz ]; then
            $log_info "$0: already prepared: $rawdir"
            continue
        fi

        ok_count=0
        bad_count=0

        for gzfile in $(ls $rawdir/*.gz); do
            $log_info "$0: zcat $gzfile"
            file=$(echo $gzfile|sed 's/\.gz//g')
            zcat $gzfile > $file
            if privacy_ok $file; then
                $log_info "$0: privacy ok: $file"
                ok_count=$(($ok_count + 1))
                $log_info "$0: tar -rf $(basename $file)"
                tar -C $rawdir -rf $rawdir/$tarball $(basename $file)
            else
                $log_info "$0: bad privacy: $file"
                bad_count=$(($bad_count + 1))
            fi
        done

        $log_always "$rawdir: ok_count: $ok_count, bad_count: $bad_count"

        # For when there is nothing we cannot publish
        if ! test -f $rawdir/$tarball; then
            continue
        fi

        $log_info "gzip -9 $rawdir/$tarball"
        gzip -9 $rawdir/$tarball
        (
        cd $rawdir && git add $tarball.gz && \
          git commit -m "Add $rawdir" $tarball.gz
        )

        #
        # Empty line to separate per-directory logs in the
        # report mailed by cron.
        #
        $log_info ""
    done
}

#
# Find all the results.tar.gz files below a given directory
# and publish them at a remote location.
# This is the last step of the deployment pipeline and it runs
# after the postprocessing phase.
#
publish()
{
    dryrun=0
    remote=server-nexa.polito.it:releases/data/
    log_info=:
    noisy=''

    options=$(getopt nR:v $*)
    if [ $? -ne 0 ]; then
        echo "Usage: publish [-nv] [-R remote] localdir..." 2>&1
        exit 1
    fi

    # Do not tollerate errors
    set -e

    set -- $options

    while [ $# -ge 0 ]; do
        if [ "$1" = "-n" ]; then
            dryrun=1
            shift
        elif [ "$1" = "-R" ]; then
            remote=$2
            shift
            shift
        elif [ "$1" = "-v" ]; then
            log_info=echo
            noisy='-v'
            shift
        elif [ "$1" = "--" ]; then
            shift
            break
        fi
    done

    for rawdir in $*; do
        for file in $(cd $rawdir && find . -type f -name results.tar.gz); do
            rm -rf /tmp/neubot-data-collect
            mkdir /tmp/neubot-data-collect
            tar -C /tmp/neubot-data-collect -xzf $rawdir/$file
            for result in $(find /tmp/neubot-data-collect -type f); do
                $log_info "$0: check_privacy $result"
                privacy_ok $result
            done
            if [ $dryrun -eq 0 ]; then
                $log_info "$0: upload tarball"
                cd $rawdir && rsync -aR $noisy $file $remote
            fi
        done
    done
}

usage="Usage: collect.sh pull|prepare|publish [options] [arguments]"

if [ $# -eq 0 ]; then
    echo $usage
    exit 0
elif [ "$1" = "pull" ]; then
    shift
    pull $*
elif [ "$1" = "prepare" ]; then
    shift
    prepare $*
elif [ "$1" = "publish" ]; then
    shift
    publish $*
else
    echo "Unknown command: $1"
    echo $usage
    exit 1
fi
