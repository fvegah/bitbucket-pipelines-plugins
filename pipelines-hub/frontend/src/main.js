import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import RunsView from './views/RunsView.vue'
import RunDetailView from './views/RunDetailView.vue'
import EnvironmentsView from './views/EnvironmentsView.vue'
import AccountsView from './views/AccountsView.vue'
import PullRequestsView from './views/PullRequestsView.vue'
import KubernetesView from './views/KubernetesView.vue'
import ServersView from './views/ServersView.vue'
import ServerDetailView from './views/ServerDetailView.vue'
import PullRequestDetailView from './views/PullRequestDetailView.vue'
import './styles.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'runs', component: RunsView, meta: { title: 'Ejecuciones' } },
    { path: '/runs/:id', name: 'run', component: RunDetailView, props: true, meta: { title: 'Ejecución' } },
    { path: '/prs', name: 'prs', component: PullRequestsView, meta: { title: 'Pull requests' } },
    { path: '/prs/:id', name: 'pr', component: PullRequestDetailView, props: true, meta: { title: 'Pull request' } },
    { path: '/entornos', name: 'environments', component: EnvironmentsView, meta: { title: 'Entornos' } },
    { path: '/k8s', name: 'k8s', component: KubernetesView, meta: { title: 'Kubernetes' } },
    { path: '/servidores', name: 'servers', component: ServersView, meta: { title: 'Servidores' } },
    { path: '/servidores/:id', name: 'server', component: ServerDetailView, props: true, meta: { title: 'Servidor' } },
    { path: '/cuentas', name: 'accounts', component: AccountsView, meta: { title: 'Cuentas' } },
  ],
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Pipelines Hub` : 'Pipelines Hub'
})

createApp(App).use(router).mount('#app')
