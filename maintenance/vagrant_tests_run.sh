#!/bin/bash

set -e

run_test() {
    box=$1
    branch=$2
    thetest=$3
    echo "testing box $box"
    cd "vagrant/$box"
    ./outside.sh "$branch" "$thetest" \
        > >(awk '{printf "%-20s %s\n", "'$box':", $0}') \
        2> >(awk '{printf "%-20s %s\n", "'$box':", $0}') \
            || echo "failure of outside.sh script for box $box"
    cd ../..
    echo "done testing box $box"
}

pidfile='/tmp/vagrant_tests_run.pid'

mode=$1
branch=$2
thetest=$3

if [ -z "$branch" -o -z "$thetest" ]; then
    echo 'usage: vagrant_tests_run.sh [ser|par] <branch> <test>'
    exit 1
fi

if [ -f "$pidfile" ] ; then
    echo "already running, found pidfile $pidfile"
    exit 1
fi

echo $$ >"$pidfile"

rm -f vagrant/*/*.out

for box in `ls vagrant` ; do
    cd "vagrant/$box"
    vagrant halt
    cd ../..
done


case $mode in

    "ser")

        for box in `ls vagrant` ; do
            run_test "$box" "$branch" "$thetest"
        done

    ;;

    "par")

        i=0
        for box in `ls vagrant` ; do
            sleep 10  # prevent some race condition in vm startup
            run_test "$box" "$branch" "$thetest" &
            pids[${i}]=$!
            let 'i+=1'
        done
        for pid in ${pids[*]}; do
            wait $pid || echo "no process with pid $pid to wait for"
        done

    ;;

    *)
        echo "invalid mode"
        exit 1

    ;;

esac

rm "$pidfile"
