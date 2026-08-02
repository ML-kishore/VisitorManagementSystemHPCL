from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth.models import User, auth
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.decorators import login_required
from .models import Host, Meeting
from .forms import *
from django.conf import settings
from email.mime.image import MIMEImage
from django.utils import timezone
import datetime
import requests
from django.shortcuts import get_object_or_404

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)

from email.mime.image import MIMEImage
import json

# Create your views here.

@login_required(login_url='/admin_login/')
def dashboard(request):
    form = Meeting_form()
    hosts = Host.objects.filter(status=True).order_by('host_name')

    return render(request, 'dashboard.html', {'form': form,'hosts': hosts})

## Verifies that only Admin uses these options and redirects them to required webpage respectively
def verify(request):
    if request.method == 'POST':
        key = request.POST.get('password')
        user = auth.authenticate(username=request.user.username,password=key)
        if user is not None:
            if request.POST.get('profile'):
                form = Add_profile()
                return render(request, 'profile_manager.html', {'form' : form})

            if request.POST.get('logout'):
                auth.logout(request)
                return redirect('/')

            if request.POST.get('meeting'):
                meetings = Meeting.objects.all().order_by('-date', '-time_in')

                return render(
                    request,
                    'meeting_history.html',
                    {'meetings': meetings}
                )
        
        # When wrong password is given
        else:
            messages.warning(request,'Please enter valid credentials !!')
            return redirect('/dashboard')

    else:
        return redirect('/dashboard')

@login_required(login_url='/admin_login/')
def meeting_manager(request):
    if request.method == 'POST':

        # If visitor button is clicked, visitor details are shown
        if visitor_id := request.POST.get("visitor"):
            meeting = Meeting.objects.filter(id=visitor_id).first()
            host = Host.objects.filter(current_meeting_id=visitor_id).first()

            if not meeting:
                # Clear stale meeting reference from host if present
                if host:
                    host.current_meeting_id = None
                    host.status = True
                    host.save()

                messages.warning(request, "This visitor record no longer exists.")
                return redirect('dashboard')

            return render(request, 'visitor_details.html', {
                'meeting': meeting,
                'host': host,
            })

        # Opens the meeting form
        elif request.POST.get("meeting"): 
            # Opens the meeting form
            form = Meeting_form()
            # hosts = Host.objects.filter(status=True)
            hosts = Host.objects.all()
            param = {'form': form,'hosts': hosts}
            return render(request, 'meeting_form.html',param)

    else:
        return redirect('/dashboard')

# Saves the visitor details filled in meeting form
@login_required(login_url='/admin_login/')
def save_meeting(request):
    if request.method == 'POST':
        host_id = request.POST.get('host')
        if not host_id:
            messages.error(request,"Please select a host.")
            return redirect('/dashboard')
        host = Host.objects.get(id=host_id)
        
        form = Meeting_form(request.POST,request.FILES)
        if form.is_valid():
            instance = form.save(commit=False)
            instance.time_in = timezone.localtime().now()
            instance.host = host.host_name
            instance.save()
            host.current_meeting_id = instance.id
            host.status = False
            host.save()
            rec = [host.host_email]
            subject = instance.visitor_name +" Checked In !"
            visitor = instance
            ## EMAIL AND SMS TO HOST
            email(subject,visitor,rec)
            # sendsms(subject,visitor,host)
            messages.success(request,'Information sent to Host, You will be called shortly !!')
            return redirect('checkin_success',meeting_id=instance.id)
        else:
            print(form.errors)
            messages.error(request,"Please correct the errors and try again.")
            return redirect('/dashboard')
    else:
        return redirect('/dashboard')
    


@login_required(login_url='/admin_login/')
def checkin_success(request, meeting_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    return render(request, 'checkin_success.html', {'meeting': meeting})


@login_required(login_url='/admin_login/')
def download_meeting_pdf(request, meeting_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)

    # Response setup
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="visitor_meeting_{meeting.id}.pdf"'

    # Document layout
    document = SimpleDocTemplate(
        response, pagesize=A4,
        rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm
    )

    # Typography styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'HealthPlusTitle', parent=styles['Title'], alignment=TA_CENTER,
        textColor=colors.HexColor('#0068A5'), fontSize=22, spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'HealthPlusSubtitle', parent=styles['Normal'], alignment=TA_CENTER,
        textColor=colors.HexColor('#666666'), fontSize=11, spaceAfter=18
    )
    heading_style = ParagraphStyle(
        'SectionHeading', parent=styles['Heading2'],
        textColor=colors.HexColor('#0068A5'), fontSize=15, spaceAfter=10
    )

    # Build PDF elements
    elements = [
        Paragraph('HPCL', title_style),
        Paragraph('Visitor Check-In Receipt', subtitle_style)
    ]

    # Optional visitor photo
    if meeting.visitor_photo:
        try:
            visitor_image = Image(meeting.visitor_photo.path, width=40 * mm, height=40 * mm)
            visitor_image.hAlign = 'CENTER'
            elements.extend([visitor_image, Spacer(1, 8 * mm)])
        except Exception as error:
            print('PDF IMAGE ERROR:', repr(error))

    elements.append(Paragraph('Visitor Information', heading_style))

    # Details table content
    checkin_time = (
        f"{meeting.date.strftime('%d %B %Y')}, "
        f"{meeting.time_in.strftime('%I:%M %p')}"
        if meeting.date and meeting.time_in
        else 'Not available'
    )
    details = [
        ['Visitor Name', meeting.visitor_name],
        ['Phone Number', str(meeting.visitor_phone)],
        ['Email Address', meeting.visitor_email],
        ['Host', meeting.host],
        ['Check-In Time', checkin_time],
        ['Status', 'CHECKED IN'],
    ]

    # Table styling
    details_table = Table(details, colWidths=[55 * mm, 105 * mm])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F1F7FA')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#003F66')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.7, colors.HexColor('#D7E0E5')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        # Highlight Status row cell
        ('BACKGROUND', (1, 5), (1, 5), colors.HexColor('#E8F5E9')),
        ('TEXTCOLOR', (1, 5), (1, 5), colors.HexColor('#1A8C0B')),
        ('FONTNAME', (1, 5), (1, 5), 'Helvetica-Bold'),
    ]))

    # Final layout compilation
    elements.extend([
        details_table,
        Spacer(1, 15 * mm),
        Paragraph('This document confirms that the visitor successfully checked in to HPCL.', subtitle_style)
    ])

    document.build(elements)
    return response

## Checkout function when Host clicks checkout button
def checkout(request):
    if request.method == 'GET':
        meeting_id = request.GET['mid']
        meeting = Meeting.objects.get(id = meeting_id)
        host = next(iter(Host.objects.filter(current_meeting_id=meeting_id)), None)
        # If checkout button already clicked
        if (meeting.time_out != None) and (host==None):
            return HttpResponse(meeting.visitor_name+', Already Checked Out !!')
        host.status = True
        host.current_meeting_id = None 
        meeting.time_out = timezone.localtime().now()
        host.save()
        meeting.save()
        rec = [meeting.visitor_email]
        Subject = "HealthPlus Meeting Details"
        visitor = meeting
        # sending email to visitor
        email(Subject,visitor,rec,host)
        return HttpResponse(meeting.visitor_name+', Checked Out Successfully !!')

# profile manager that saves host profile
@login_required(login_url='/admin_login/')
def profile_manager(request):
    if request.method=='POST':
        form = Add_profile(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('/dashboard')
    else:
        return redirect('/dashboard')

# Checks for the given id in host database and fills the add profile form automatically with it
@login_required(login_url='/admin_login/')
def edit_profile(request):
    if request.method == 'POST':
        host_id = request.POST.get('editing')
        instance = Host.objects.filter(id=host_id).first()
        form = Add_profile(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            form.save()
            return redirect('/dashboard')
    else:
        return redirect('/dashboard')

# checks which button was clicked, either edit or delete and redirects them respectively
@login_required(login_url='/admin_login/')
def edit_delete(request):
    if request.method=='POST':
        host_id =request.POST.get('id')
        if host_id=='':
            # If invalid profile id was given
            messages.warning(request,'Please enter a valid profile Id first !!')
            form = Add_profile()
            return render(request, 'profile_manager.html', {'form' : form})
        host = Host.objects.filter(id=host_id).first()
        if host:
            if request.POST.get('edit'):
                form = Add_profile(instance=host)
                context = {'form':form,'edit':True,'info':host_id}
                return render(request, 'profile_manager.html',context)
            elif request.POST.get('delete'):
                host.delete()
                return redirect('/dashboard')
        else:
            # If no profile was found
            messages.warning(request,'Profile not found !!')
            form = Add_profile()
            return render(request, 'profile_manager.html', {'form' : form})
    else:
        return redirect('/dashboard')


# Sends the email to both host and visitor


def email(subject, visitor, rec, host=None):

    sender = settings.EMAIL_HOST_USER
    if host:
        html_content = render_to_string(
            'visitor_mail_template.html',
            {
                'visitor': visitor,
                'host': host
            }
        )
    else:
        html_content = render_to_string(
            'host_mail_template.html',
            {
                'visitor': visitor
            }
        )

    text_content = strip_tags(html_content)

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=sender,
            to=rec
        )

        msg.attach_alternative(
            html_content,
            "text/html"
        )

        # Embed the visitor photo inside the host email
        if not host and visitor.visitor_photo:

            with visitor.visitor_photo.open('rb') as image_file:

                image = MIMEImage(
                    image_file.read()
                )

                image.add_header(
                    'Content-ID',
                    '<visitor_photo>'
                )

                image.add_header(
                    'Content-Disposition',
                    'inline',
                    filename=visitor.visitor_photo.name
                )

                msg.attach(image)

        try:
            msg.send()
        except Exception as e:
            print("Email sending failed:", e)

        print(
            f"Email sent successfully to: {rec}"
        )

    except Exception as e:

        print(
            "EMAIL ERROR:",
            repr(e)
        )

        raise


# # Sends the SMS to host
# def sendsms(subject,visitor,host):
#     URL = 'https://www.way2sms.com/api/v1/sendCampaign'
#     msg = "Hey, "+host.host_name+", Your Upcoming meeting is with : "+visitor.visitor_name+", Contact no. : "+str(visitor.visitor_phone)+", Email Id : "+visitor.visitor_email+". Check-In Time is : "+str(visitor.time_in)[11:16]
#     ## FILL IN YOUR DETAILS HERE
#     req_params = {
#     'apikey':'your api key',
#     'secret':'your secret key',
#     'usetype':'stage',
#     'phone': '+91'+str(host.host_phone),
#     'message':msg,
#     'senderid':'your way2sms account email id'
#     }
#     # try except block to avoid wesite crashing due to SMS error
#     try:
#         requests.post(URL, req_params)
#     except:
#         pass
#     return
