from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required


@login_required
def home(request):
    return render(request, 'core/home.html')


def health_check(request):
    return JsonResponse({'status': 'ok'})
