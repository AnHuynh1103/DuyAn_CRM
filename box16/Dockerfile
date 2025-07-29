# Build a new image based on:
# FROM novobidevops/odoo:15
#      novobidevops/odoo:14
#      novobidevops/odoo:13
#      novobidevops/odoo:12

FROM novobidevops/odoo:18

# Example 1: Install new python libs in the new image
# RUN pip3 install --no-cache-dir paramiko

# Example 2: Install new python libs from the requirement file
RUN pip install --upgrade pip
RUN pip3 install google-api-python-client
RUN pip3 install google-auth-httplib2
RUN pip3 install google-auth-oauthlib
RUN pip3 install oauth2client
RUN pip3 install SkPy
RUN pip3 install pytz
RUN pip3 install html2text
RUN pip3 install PyPDF2
# Skype SDK


# Google SDK



# COPY python3-requirements.txt /etc/
# RUN pip install --no-cache-dir -r /etc/python3-requirements.txt
# RUN rm /etc/python3-requirements.txt
