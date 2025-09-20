import multiprocessing
import re
import signal
import time
from dataclasses import dataclass

import base58
import click
import questionary
from solders.keypair import Keypair

SHOW_AT_ONCE = 10_000


@dataclass
class Wallet:
	public_key: str
	private_key: str


def wallet_matches(public_key: str, start_pattern: str, end_pattern: str) -> bool:
	"""Проверяет, удовлетворяет ли кошелек заданным условиям"""
	return (start_pattern and public_key.startswith(start_pattern)) or \
		   (end_pattern and public_key.endswith(end_pattern))


def find_wallet_worker(
	start_pattern: str,
	end_pattern: str,
	result_queue: multiprocessing.Queue,
	progress_queue: multiprocessing.Queue,
	process_id: int,
) -> None:
	"""Работник для поиска кошельков. Результат отправляется в очередь"""
	count = 0
	to_report = SHOW_AT_ONCE

	try:
		while True:
			count += 1
			to_report -= 1
			keypair = Keypair()
			public_key = str(keypair.pubkey())

			if to_report == 0:
				# Отправляем прогресс в главную очередь
				progress_queue.put((process_id, count))
				to_report = SHOW_AT_ONCE

			if wallet_matches(public_key, start_pattern, end_pattern):
				result_queue.put(Wallet(public_key, base58.b58encode(bytes(keypair)).decode()))
				break
	except KeyboardInterrupt:
		print(f'[Процесс {process_id}] Завершение работы')
		exit(0)


def display_progress(progress_queue: multiprocessing.Queue, num_processes: int) -> None:
	"""Выводит общий прогресс всех процессов"""
	progress = {i + 1: 0 for i in range(num_processes)}
	start_time = time.time()

	while True:
		try:
			# Получаем обновление из очереди прогресса
			process_id, count = progress_queue.get()
			progress[process_id] = count

			# Собираем общий прогресс
			total_processed = sum(progress.values())
			elapsed_time = time.time() - start_time
			print(
				f'\rОбработано {total_processed} кошельков за {elapsed_time:.2f} секунд',
				end='',
				flush=True
			)
		except multiprocessing.queues.Empty:
			continue


def find_wallet_parallel(start_pattern: str, end_pattern: str, num_processes: int = None) -> Wallet:
	"""Запускает параллельный поиск кошелька с заданным паттерном"""
	if num_processes is None:
		num_processes = multiprocessing.cpu_count()

	print(f'Запускаем {num_processes} процессов для поиска...')
	result_queue = multiprocessing.Queue()
	progress_queue = multiprocessing.Queue()
	processes = []

	# Запуск воркеров
	for i in range(num_processes):
		process = multiprocessing.Process(
			target=find_wallet_worker,
			args=(start_pattern, end_pattern, result_queue, progress_queue, i + 1),
			daemon=True
		)
		processes.append(process)
		process.start()

	# Запуск отдельного процесса для отслеживания прогресса
	progress_process = multiprocessing.Process(target=display_progress, args=(progress_queue, num_processes), daemon=True)
	progress_process.start()

	try:
		# Ожидаем результат от одного из воркеров
		wallet = result_queue.get()

		for process in processes:
			process.terminate()
		progress_process.terminate()  # Останавливаем процесс прогресса

		return wallet
	except KeyboardInterrupt:
		print('\nПрерывание! Завершаем все процессы...')

		for process in processes:
			process.terminate()

		progress_process.terminate()
		exit(0)


def signal_handler(sig, frame):
	"""Обработка прерывания Ctrl+C"""
	print('\nЗавершение программы...')
	exit(0)


def is_valid_pattern(s) -> bool:
	pattern = r'^[1-9A-HJ-NP-Za-km-z]+$'
	return bool(re.fullmatch(pattern, s))


@click.command()
def main():
	# 1) Выбор режима поиска
	SEARCH_MODE_ONE = 'Поиск по начальному паттерну'
	SEARCH_MODE_TWO = 'Поиск по конечному паттерну'

	search_mode = questionary.select(
		'Выберите режим поиска:',
		choices=[SEARCH_MODE_ONE, SEARCH_MODE_TWO],
		default=SEARCH_MODE_ONE
	).ask()

	# 2) Ввод паттерна и проверка на валидность
	while True:
		pattern = questionary.text('Введите паттерн (только буквы и цифры):').ask()
		pattern = pattern.strip()
		if is_valid_pattern(pattern):
			break
		else:
			print('Неверный паттерн! Пожалуйста, введите только цифры от 1 до 9 и буквы латинского алфавита (кроме I, O, L и U)')

	# 3) Выбор количества процессов
	cpu_count = multiprocessing.cpu_count()
	num_processes = questionary.select(
		f'Выберите количество процессов (от 1 до {cpu_count}):',
		choices=[str(i) for i in range(1, cpu_count + 1)],
		default=str(cpu_count)
	).ask()

	# Выводим результаты
	start_pattern = end_pattern = ''

	if search_mode == SEARCH_MODE_ONE:
		start_pattern = pattern
	else:
		end_pattern = pattern

	start_time = time.time()
	wallet = find_wallet_parallel(start_pattern, end_pattern, int(num_processes))

	elapsed_time = time.time() - start_time
	print(f'\nНайден кошелек за {elapsed_time:.2f} секунд!')
	print(f'Публичный ключ: {wallet.public_key}')
	print(f'Приватный ключ: {wallet.private_key}')


if __name__ == '__main__':
	signal.signal(signal.SIGINT, signal_handler)
	main()
