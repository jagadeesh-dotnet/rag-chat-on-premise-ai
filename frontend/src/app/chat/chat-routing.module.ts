import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { ChatComponent } from './chat/chat.component';

const routes: Routes = [
  { path: '', component: ChatComponent }, // new chat
  { path: 'c/:id', component: ChatComponent }, // a saved conversation (survives a reload)
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule],
})
export class ChatRoutingModule {}
