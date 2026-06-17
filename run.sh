#!/bin/bash


PYTHON_COMMAND="python3" #Change this to your python command / path to python binary

VENV_NAME="Open_PS_Calc_venv"

DIR_NAME=$(dirname "$0")

PYTHON_MAJVER=$($PYTHON_COMMAND -V | awk -F '.' '{ print $1 }' | awk -F ' ' '{ print $2 }')
PYTHON_MINVER=$($PYTHON_COMMAND -V | awk -F '.' '{ print $2 }')

if (( "$PYTHON_MAJVER" == 3 && "PYTHON_MINVER" >= 13 )); then
	echo "Python version that meets the requirements found: Python $PYTHON_MAJVER.$PYTHON_MINVER"
	
	cd $DIR_NAME

	if [ ! -d "./$VENV_NAME" ]; then
		$PYTHON_COMMAND -m venv create $VENV_NAME
		./$VENV_NAME/bin/python -m pip install -r requirements.txt
	fi

	PYTHON_COMMAND="./$VENV_NAME/bin/python"
	$PYTHON_COMMAND main.py
else
	echo "Required python version was not found. Aborting..."
fi
