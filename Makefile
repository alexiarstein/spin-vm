DOMAIN   = lexvm
POTFILE  = locale/$(DOMAIN).pot
LANGUAGES = es pt_BR de fr nl ja zh_CN hi

POFILES = $(foreach lang,$(LANGUAGES),locale/$(lang)/LC_MESSAGES/$(DOMAIN).po)
MOFILES = $(POFILES:.po=.mo)

.PHONY: all pot update-po compile-mo clean

all: compile-mo

# Extract translatable strings from source into the .pot template
pot:
	xgettext --language=Python --keyword=_ \
	         --package-name=$(DOMAIN) \
	         --output=$(POTFILE) \
	         lexvm.py

# Merge new strings from .pot into each existing .po file
update-po: pot
	$(foreach lang,$(LANGUAGES), \
	    msgmerge --update --backup=none \
	        locale/$(lang)/LC_MESSAGES/$(DOMAIN).po $(POTFILE);)

# Compile all .po files to binary .mo files
compile-mo: $(MOFILES)

locale/%/LC_MESSAGES/$(DOMAIN).mo: locale/%/LC_MESSAGES/$(DOMAIN).po
	msgfmt $< -o $@

clean:
	rm -f $(MOFILES) $(POTFILE)
