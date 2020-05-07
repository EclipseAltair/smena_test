# -*- coding: utf-8 -*-
import json

from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django_rq import enqueue

from .models import Check, Printer
from .wkhtmltopdf import generate_pdf


@csrf_exempt    # исключение из CSRF-проверки для CORS
def create_checks(request):    # создание чеков для заказа
    if request.method == 'POST':
        body_unicode = request.body.decode('UTF-8')
        try:
            body_data = json.loads(body_unicode)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        
        if Check.objects.filter(order__id=body_data['id']).count() != 0:    # если кол-во чеков с данным id не 0
            return JsonResponse({"error": "Для данного заказа уже созданы чеки"}, status=400)
        
        if Printer.objects.filter(point_id=body_data["point_id"]).count() == 0:    # если кол-во принтеров у точки 0
            return JsonResponse({"error": "Для данной точки не настроено ни одного принтера"}, status=400)

        kitchen_printer = Printer.objects.get(point_id=body_data['point_id'], check_type='kitchen')
        kitchen_path = f'media/pdf/{body_data["id"]}_{"kitchen"}.pdf'
        kitchen_check = Check.objects.create(printer_id=kitchen_printer, type='kitchen', order=body_data,
                                             status='new', pdf_file=kitchen_path)
        enqueue(generate_pdf, 'kitchen', kitchen_check.id, kitchen_path, body_data)    # добавление задачи в очередь
    
        client_printer = Printer.objects.get(point_id=body_data['point_id'], check_type='client')
        client_path = f'media/pdf/{body_data["id"]}_{"client"}.pdf'
        client_check = Check.objects.create(printer_id=client_printer, type='client', order=body_data, 
                                            status='new', pdf_file=client_path)
        enqueue(generate_pdf, 'client', client_check.id, client_path, body_data)    # добавление задачи в очередь

        return JsonResponse({"ok": "Чеки успешно созданы"}, status=200)
    return JsonResponse({"error": "Method Not Allowed"}, status=405)
        

def new_checks(request):    # список доступных чеков для печати
    if request.method == 'GET':
        try:
            api_key = request.GET['api_key']
        except KeyError:
            return JsonResponse({"error": "There is not api_key"}, status=400)
        
        try:
            Printer.objects.get(api_key=api_key)
        except Printer.DoesNotExist:
            return JsonResponse({"error": "Ошибка авторизации"}, status=401)
        
        rendered_checks = Check.objects.filter(printer_id__api_key=api_key, status='rendered')
        
        checks = []
        for rendered_check in rendered_checks:
            checks.append({"id": rendered_check.id})
        
        return JsonResponse({"checks": checks}, status=200)
    return JsonResponse({"error": "Method Not Allowed"}, status=405)


def get_check(request):    # pdf-файл чека
    if request.method == 'GET':
        try:
            api_key = request.GET['api_key']
        except KeyError:
            return JsonResponse({"error": "There is not api_key"}, status=400)

        try:
            check_id = int(request.GET['check_id'])
        except KeyError:
            return JsonResponse({"error": "There is not check_id"}, status=400)
        
        try:
            Printer.objects.get(api_key=api_key)
        except Printer.DoesNotExist:
            return JsonResponse({"error": "Ошибка авторизации"}, status=401)

        try:
            check = Check.objects.get(printer_id__api_key=api_key, id=check_id)
        except Check.DoesNotExist:
            return JsonResponse({"error": "Данного чека не существует"}, status=400)
        
        if check.status == 'new':
            return JsonResponse({"error": "Для данного чека не сгенерирован PDF-файл"}, status=400)
        
        check_path = check.pdf_file.path
        with open(check_path, 'rb') as f:
            pdf = f.read()
            
        response = HttpResponse(pdf, content_type='application/pdf', status=200)
        response['Content-Disposition'] = f'attachment;filename={check_path}'   # принуждение к загрузке

        Check.objects.filter(id=check_id).update(status='printed')
        
        return response
    return JsonResponse({"error": "Method Not Allowed"}, status=405)
