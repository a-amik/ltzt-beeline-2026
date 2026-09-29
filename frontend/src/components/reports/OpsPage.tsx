import { num } from '../../lib/ui'
import { IconAlert, IconChart, IconClock, IconGauge, IconMap, IconShield, IconUsers, IconWrench } from '../../lib/icons'
import type { Reports } from '../../types'
import { ArtOps } from './art'
import { Figure, LineChart, Tiles } from './charts'
import { ABUSE_NAMES, ABUSE_NOTES, FRAUD, STAND } from './facts'

const sec = (v: number) => `${num(v, v < 1 ? 2 : 1)} с`

export default function OpsPage({ reports }: { reports: Reports }) {
  const scale = (reports.scale?.rows ?? []).filter((r) => r.portfolio)
  const all = reports.scale?.rows ?? []
  const biggest = [...all].sort((a, b) => b.requests - a.requests)[0]
  const load = reports.load
  const step50 = load?.steps.find((s) => s.users === 50)
  const cap = load?.solves.find((s) => s.statuses.includes(429))

  return (
    <article className="b-an">
      <header className="b-an-hero">
        <div className="b-an-art"><ArtOps /></div>
        <p className="kick">О проекте · нагрузка и&nbsp;безопасность</p>
        <h1>Нагрузка и&nbsp;безопасность: что проверено в&nbsp;прототипе</h1>
        <p className="lede">
          Мы проверили расчёт на&nbsp;участках до&nbsp;2000 заявок и&nbsp;200 бригад, а&nbsp;сервис&nbsp;— при одновременной работе нескольких
          экранов, параллельных расчётах и&nbsp;некорректных запросах. Проверка выявила три проблемы: сценарий имитации принимал
          до&nbsp;10&nbsp;000 новых заявок, размер загружаемого файла не&nbsp;ограничивался, а&nbsp;число одновременных расчётов не&nbsp;сдерживалось.
          Ограничения добавлены и&nbsp;проверены повторными запросами.
        </p>
        <Tiles items={[
          { value: biggest ? sec(biggest.elapsed_s) : '—', icon: <IconGauge />, label: biggest ? `план на ${num(biggest.requests)} заявок` : 'масштаб не замерен', note: biggest ? `${num(biggest.engineers)} бригад, ${num(biggest.rss_mb_after)} МБ памяти` : undefined },
          { value: step50 ? `${num(step50.rps)}/с` : '—', icon: <IconChart />, label: 'чтений при 50 экранах', note: step50 ? `95 % ответов до ${num(step50.p95_ms)} мс; ошибок ${step50.errors}` : 'нагрузка ещё не измерена' },
          { value: cap ? '429' : '—', icon: <IconShield />, label: 'ответ лишнему расчёту', note: 'одновременно работают не более трёх расчётов' },
          { value: String(load?.fixed?.length ?? 0), icon: <IconWrench />, label: 'исправленных проблем', note: 'сценарий, размер файла, очередь расчётов' },
        ]} />
      </header>

      {scale.length ? (
        <section id="o-scale">
          <h2><span className="ic"><IconClock /></span>Время расчёта при&nbsp;разном числе заявок</h2>
          <p>
            Для проверки мы увеличили участки на&nbsp;основе данных заказчика: сохранили время визитов, навыки и&nbsp;длительность работ,
            а&nbsp;адреса разместили поблизости. Поиск ограничен 4&nbsp;секундами. На&nbsp;графике отдельно показаны время до&nbsp;первого
            допустимого плана и&nbsp;полное время расчёта, включая подготовку данных и&nbsp;улучшение плана.
          </p>
          <Figure n={1} title="Время расчёта по&nbsp;размеру участка, секунды" legend={[
            { label: 'первое решение', color: 'var(--race-control)' }, { label: 'всего', color: 'var(--race-ours)' }]}>
            <LineChart x={scale.map((r) => `${num(r.requests)}×${num(r.engineers)}`)} lo={0} hi={Math.ceil(Math.max(...scale.map((r) => r.elapsed_s)) / 10) * 10}
              fmt={(v) => sec(v)} series={[
                { key: 'first', label: 'первое решение', color: 'var(--race-control)', values: scale.map((r) => r.first_solution_s), dots: true },
                { key: 'all', label: 'всего', color: 'var(--race-ours)', values: scale.map((r) => r.elapsed_s), dots: true },
              ]} />
          </Figure>
          <table className="b-an-table num">
            <thead><tr><th>Заявок × бригад</th><th>Первое решение</th><th>Всего</th><th>Назначено</th><th>Память</th></tr></thead>
            <tbody>{scale.map((r) => (
              <tr key={r.requests}><td>{num(r.requests)} × {num(r.engineers)}</td><td>{sec(r.first_solution_s)}</td><td>{sec(r.elapsed_s)}</td>
                <td>{num(r.assigned)} из {num(r.requests)}</td><td>{num(r.rss_mb_after)} МБ</td></tr>
            ))}</tbody>
          </table>
        </section>
      ) : null}

      {load ? (
        <section id="o-load">
        <h2><span className="ic"><IconUsers /></span>Одновременная работа экранов</h2>
          <p>
            При проверке каждый экран запрашивал набор заявок, последний план, данные контроля и&nbsp;отчёты. Одна копия сервиса
            обслуживала от&nbsp;{load.steps[0]?.users} до&nbsp;{load.steps[load.steps.length - 1]?.users} одновременных экранов.
            Не&nbsp;более трёх тяжёлых расчётов выполняются одновременно. Следующий запрос получает код 429 и&nbsp;может повториться
            через пять секунд; чтение данных в&nbsp;это время продолжается.
          </p>
          <Figure n={2} title="Время ответа при&nbsp;разном числе экранов, миллисекунды" legend={[
            { label: 'медиана', color: 'var(--race-control)' }, { label: 'p95', color: 'var(--race-ours)' }, { label: 'p99', color: 'var(--race-baseline)', dashed: true }]}
            note={`Медиана — половина ответов быстрее этого времени; p95 — 95 %, p99 — 99 %. Проверка: ${load.base.replace('http://', '')}, набор ${load.dataset}. Ошибок: ${load.steps.reduce((a, s) => a + s.errors, 0)}.`}>
            <LineChart x={load.steps.map((s) => `${s.users} экр.`)} lo={0} hi={Math.ceil(Math.max(...load.steps.map((s) => s.p99_ms)) / 1000) * 1000}
              fmt={(v) => `${num(v)} мс`} series={[
                { key: 'p50', label: 'медиана', color: 'var(--race-control)', values: load.steps.map((s) => s.p50_ms), dots: true },
                { key: 'p95', label: 'p95', color: 'var(--race-ours)', values: load.steps.map((s) => s.p95_ms), dots: true },
                { key: 'p99', label: 'p99', color: 'var(--race-baseline)', values: load.steps.map((s) => s.p99_ms), dashed: true },
              ]} />
          </Figure>
          <table className="b-an-table num">
            <thead><tr><th>Расчётов одновременно</th><th>Самый долгий</th><th>Коды ответа</th><th>Чтение в это время, p95</th></tr></thead>
            <tbody>{load.solves.map((s) => (
              <tr key={s.parallel}><td>{s.parallel}</td><td>{sec(s.slowest_s)}</td><td>{s.statuses.join(', ')}</td><td>{num(s.read_during_p95_ms)} мс</td></tr>
            ))}</tbody>
          </table>
        </section>
      ) : null}

      {load?.abuse.length ? (
        <section id="o-abuse">
          <h2><span className="ic"><IconAlert /></span>Как сервис отвечает на&nbsp;некорректные запросы</h2>
          <p>Мы отправили запросы, которых нет в&nbsp;обычной работе экрана. Сервис должен быстро отклонить их и&nbsp;продолжить обслуживать другие запросы.</p>
          <table className="b-an-table">
            <thead><tr><th>Запрос</th><th>Ответ</th><th>Время</th><th>Что было</th></tr></thead>
            <tbody>{load.abuse.map((a) => (
              <tr key={a.case}><td>{ABUSE_NAMES[a.case] ?? a.case}</td><td>{String(a.status)}</td><td>{sec(a.seconds)}</td><td className="muted">{ABUSE_NOTES[a.case] ?? a.note ?? ''}</td></tr>
            ))}</tbody>
          </table>
        </section>
      ) : null}

      <section id="o-sec">
        <h2><span className="ic"><IconShield /></span>Данные и&nbsp;доступ</h2>
        <div className="b-an-cards">
          <div><h4>Что хранится</h4><p>Заявки дня: адрес, окно, тип работ. Имён и&nbsp;телефонов клиентов в&nbsp;данных нет. Исходные файлы заказчика в&nbsp;публичный репозиторий не&nbsp;входят.</p></div>
          <div><h4>Кто что меняет</h4><p>В&nbsp;прототипе диспетчеру доступны ручной приоритет и&nbsp;время поиска; остальные настройки показаны руководителю. Значения ограничены схемой. Для&nbsp;пилота права нужно проверять на&nbsp;сервере.</p></div>
          <div><h4>Стенд</h4><p>{STAND.url.replace('https://', '')}: Yandex Cloud, {STAND.machine}; вход через API Gateway, сертификат до&nbsp;{STAND.certUntil}, поисковикам закрыт.</p></div>
        </div>
      </section>

      <section id="o-fraud">
        <h2><span className="ic"><IconMap /></span>Проверка отметок бригады</h2>
        <p>
          Бонус начисляется только за&nbsp;подтверждённую работу. Восемь признаков помогают заметить сомнительные отметки.
          Каждый такой сигнал требует проверки диспетчером и&nbsp;сам по&nbsp;себе не&nbsp;доказывает нарушение.
        </p>
        <ul className="b-an-chips">{FRAUD.map((f) => <li key={f}>{f}</li>)}</ul>
      </section>

      <section id="o-next">
        <h2><span className="ic"><IconShield /></span>Для пилота</h2>
        <ul>
          <li>Вход по&nbsp;учётной записи заказчика; права доступа должны определяться на&nbsp;сервере.</li>
          <li>Хранение планов и&nbsp;отметок в&nbsp;базе данных: сейчас они теряются при&nbsp;перезапуске сервиса.</li>
          <li>Две копии сервиса за&nbsp;балансировщиком и&nbsp;очередь расчётов между ними.</li>
          <li>Отметки из&nbsp;приложения бригады вместо расчётных отметок по&nbsp;плану.</li>
        </ul>
      </section>
    </article>
  )
}
