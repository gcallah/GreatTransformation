# A template makefile that works for static websites.
# Need to export TEMPLATE_DIR as ENV var
export TEMPLATE_DIR = templates
# Export MARKDOWN_DIR
export MARKDOWN_DIR = md
PTML_DIR = html_src
UTILS_DIR = utils
DOCKER_DIR = docker
# REPO = this repo!

FORCE:

tests: FORCE
	echo "Here is where you should run your tests."

github:
	-git commit -a 
	git push origin master

nocrud:
	rm *~
	rm .*swp
	rm $(PTML_DIR)/*~
	rm $(PTML_DIR)/.*swp
